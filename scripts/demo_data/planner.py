"""Build the full chronological synthetic event plan for one location.

Reads pre-built per-item profiles (item_profiles.json, see build_profiles.py --
this file does NOT touch log.csv or fit anything at runtime). For each item,
per storage: a global, item-independent cadence decides how often it gets
checked; individual TAKEOUT scans are generated directly from that item's own
scans_per_day/qty_mean/qty_sigma (Poisson count of scans x lognormal size each,
scaled by the location multiplier and the real year-over-year trend); the
running balance is decremented by the true total; the COUNT observed is that
balance plus small measurement noise, clipped to the item's real max_quantity.
A restock only fires when the observed count drops to/below a per-checkpoint
stochastic trigger point centered on the item's real min_quantity, sized to
bring it back to max_quantity and rounded up to its real batch_size.

Plus a small separate TRANSFER stream, a location-independent UNKNOWN_UPC
stream, and a same-item error/correction pass. Everything is a PlannedEvent;
replay.py is the only thing that touches the database.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta

import numpy as np

import config as cfg
from profiles import CatalogProfiles, ExpirationBehavior, ItemGenerationProfile


@dataclass(slots=True)
class PlannedEvent:
    ts: datetime
    kind: str  # "scan" | "bulk_session" | "unknown_upc_scan" | "unknown_upc_resolve"

    # kind == "scan"
    item_name: str | None = None
    operation_type: str | None = None
    quantity: int | None = None
    from_storage: str | None = None
    to_storage: str | None = None
    admin_action: bool = False
    expiration_allocations: list[tuple[date | None, int]] | None = None

    # kind == "bulk_session" (always single-item -- each item gets its own bulk_session events)
    counts: dict[tuple[str, str], int] = field(default_factory=dict)  # (item_name, storage_name) -> qty
    restocks: dict[tuple[str, str], int] = field(default_factory=dict)
    restock_expirations: dict[str, list[tuple[date | None, int]]] = field(default_factory=dict)  # storage_name -> allocations
    count_expirations: dict[str, list[tuple[date | None, int]]] = field(default_factory=dict)  # storage_name -> allocations

    # kind == "unknown_upc_scan" / "unknown_upc_resolve"
    upc: str | None = None
    resolve_to_item_name: str | None = None


@dataclass(slots=True)
class RefData:
    hour_mult: np.ndarray  # len 24
    dow_mult: np.ndarray  # len 7, Mon=0
    month_mult: np.ndarray  # len 12, Jan=0
    catalog: CatalogProfiles


def load_refdata() -> RefData:
    tmult = json.loads((cfg.REFERENCE_DIR / "time_multipliers.json").read_text())
    catalog = CatalogProfiles.model_validate_json((cfg.REFERENCE_DIR / "item_profiles.json").read_text())

    hour_mult = np.array([tmult["hour_of_day"][str(h)] for h in range(24)])
    dow_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    dow_mult = np.array([tmult["day_of_week"][d] for d in dow_order])
    month_order = [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    ]
    month_mult = np.array([tmult["month_of_year"][m] for m in month_order])

    return RefData(hour_mult, dow_mult, month_mult, catalog)


# ---------------------------------------------------------------- sampling primitives
def _day_weight(d: date, ref: RefData) -> float:
    return ref.dow_mult[d.weekday()] * ref.month_mult[d.month - 1]


def _sample_days(rng: np.random.Generator, day_range: list[date], weights: np.ndarray, n: int) -> np.ndarray:
    if n <= 0:
        return np.array([], dtype=object)
    probs = weights / weights.sum()
    return rng.choice(np.array(day_range, dtype=object), size=n, p=probs)


def _sample_timestamp_for_day(rng: np.random.Generator, day: date, ref: RefData) -> datetime:
    hour = rng.choice(24, p=ref.hour_mult / ref.hour_mult.sum())
    second_of_hour = int(rng.integers(0, 3600))
    return datetime.combine(day, time(hour=int(hour))) + timedelta(seconds=second_of_hour)


def _lognormal_from_mean(rng: np.random.Generator, mean: float, sigma: float) -> float:
    """Draw from a lognormal whose MEAN is exactly `mean` (not its median) --
    avoids the common bias of treating the mean as the lognormal's mu."""
    mu = np.log(max(mean, 1e-6)) - sigma**2 / 2
    return float(rng.lognormal(mu, sigma))


def _shelf_life_days(rng: np.random.Generator) -> int:
    jitter = rng.uniform(1 - cfg.RESTOCK_SHELF_LIFE_JITTER, 1 + cfg.RESTOCK_SHELF_LIFE_JITTER)
    return max(1, round(cfg.RESTOCK_SHELF_LIFE_DAYS * jitter))


# ---------------------------------------------------------------- global cadence (not fit per item, on purpose)
def plan_item_session_times(location_multiplier: float, window_start: date, window_end: date, ref: RefData, rng: np.random.Generator) -> list[datetime]:
    """One shared check-in cadence, applied independently to every item -- not
    derived from that item's own usage rate. Busier locations check more often.

    Every item's timeline starts with this forced initial COUNT within the
    first few days -- otherwise the normal 20-250 day gap to the first
    scheduled checkpoint left a long stretch where TAKEOUT scans could occur
    before anything ever established what was actually on the shelf (a real
    system can't log a takeout of an item it hasn't counted in yet)."""
    times: list[datetime] = [_sample_timestamp_for_day(rng, window_start + timedelta(days=int(rng.integers(1, 5))), ref)]
    t = window_start
    while True:
        gap_days = max(1, round(_lognormal_from_mean(rng, cfg.COUNT_INTERVAL_MEAN_DAYS, cfg.COUNT_INTERVAL_SIGMA) / max(location_multiplier, 0.1)))
        gap_days = int(np.clip(gap_days, *cfg.COUNT_INTERVAL_CLIP_DAYS))
        t = t + timedelta(days=gap_days)
        if t >= window_end:
            break
        times.append(_sample_timestamp_for_day(rng, t, ref))
    if not times or (window_end - times[-1].date()).days > 14:
        times.append(_sample_timestamp_for_day(rng, window_end - timedelta(days=int(rng.integers(1, 8))), ref))
    return times


def _apply_scan_compliance(rng: np.random.Generator, true_qty: float) -> int | None:
    roll = rng.random()
    if roll < cfg.GUEST_FORGOT_RATE:
        return None
    if roll < cfg.GUEST_FORGOT_RATE + cfg.GUEST_UNDER_RATE:
        return max(1, round(true_qty * rng.uniform(0.3, 0.8)))
    if roll < cfg.GUEST_FORGOT_RATE + cfg.GUEST_UNDER_RATE + cfg.GUEST_OVER_RATE:
        return round(true_qty * rng.uniform(1.3, 2.0))
    return max(1, round(true_qty))


# ---------------------------------------------------------------- expiration lots (FEFO)
@dataclass(slots=True)
class _ExpirationLots:
    """Minimal per-storage ledger of open dated lots, oldest first -- just
    enough state to make "takes the soonest-expiring lot" a real mechanic
    instead of an unconnected random date draw."""

    lots: list[list]  # [expires_on, quantity], sorted ascending by date; mutated in place

    def add(self, expires_on: date, qty: int) -> None:
        if qty <= 0:
            return
        self.lots.append([expires_on, qty])
        self.lots.sort(key=lambda lot: lot[0])

    def take(self, rng: np.random.Generator, qty: int, expiration: ExpirationBehavior) -> list[tuple[date | None, int]]:
        """Consume `qty` units per FEFO-ish behavior. The real app validates that
        allocations sum to the action's full quantity whenever the item is
        expiration-tracked -- there's no "log nothing" option -- so "forgot" means
        logging the full amount as an unspecified date, not an empty allocation."""
        if qty <= 0:
            return []
        roll = rng.random()
        if roll < expiration.forgot_log_rate:
            self._consume_fefo(qty)  # physically still comes from the front; logged as unspecified-date
            return [(None, qty)]
        if not self.lots:
            return [(None, qty)]  # nothing tracked yet -- still must cover the full quantity
        pick_wrong = roll < expiration.forgot_log_rate + expiration.wrong_pick_rate and len(self.lots) > 1
        index = int(rng.integers(1, len(self.lots))) if pick_wrong else 0
        return self._consume_at(index, qty)

    def _consume_fefo(self, qty: int) -> None:
        self._consume_at(0, qty)

    def reconcile(self, observed: int) -> list[tuple[date | None, int]]:
        """A physical COUNT is ground truth. If the ledger believes more is on
        hand than was actually counted, trim the soonest-expiring lots first
        (oldest stock is what's most likely already gone). If it believes less,
        the extra is real but untracked -- log it as unspecified-date. Returns
        the allocation for the COUNT action itself, which must sum to `observed`
        (same real-app rule as every other op type on a tracked item)."""
        lot_total = sum(qty for _, qty in self.lots)
        if lot_total > observed:
            self._consume_at(0, lot_total - observed)
        allocations: list[tuple[date | None, int]] = [(d, q) for d, q in self.lots]
        shortfall = observed - sum(q for _, q in allocations)
        if shortfall > 0:
            allocations.append((None, shortfall))
        return allocations

    def _consume_at(self, index: int, qty: int) -> list[tuple[date | None, int]]:
        result: list[tuple[date | None, int]] = []
        remaining = qty
        while remaining > 0 and self.lots:
            index = min(index, len(self.lots) - 1)
            expires_on, available = self.lots[index]
            take = min(available, remaining)
            self.lots[index][1] -= take
            remaining -= take
            result.append((expires_on, take))
            if self.lots[index][1] <= 0:
                self.lots.pop(index)
                index = 0
        if remaining > 0:
            # The tracked lot ledger ran short of what's being taken (e.g. the
            # starting "pre-stocked" balance was never backed by a real lot) --
            # the allocation must still sum to exactly `qty`, so the shortfall
            # becomes an unspecified-expiration remainder rather than a mismatch.
            result.append((None, remaining))
        return result


def build_item_events(
    item_name: str,
    profile: ItemGenerationProfile,
    storages: list[str],
    location_multiplier: float,
    rng: np.random.Generator,
    ref: RefData,
    window_start: date,
    window_end: date,
    disabled_features: frozenset[str] = frozenset(),
) -> list[PlannedEvent]:
    events: list[PlannedEvent] = []
    n_storages = max(len(storages), 1)
    session_times = plan_item_session_times(location_multiplier, window_start, window_end, ref, rng)
    balances = {s: float(profile.max_quantity) for s in storages}  # start "recently stocked"
    expiration_tracked = profile.expiration.tracked and "expiration" not in disabled_features
    if expiration_tracked:
        # Seed with an assumed dated lot matching the same "recently stocked" assumption
        # the balance itself already makes -- starting empty instead would make the very
        # first COUNT 100% "unspecified" (the real app only records known-dated portions
        # to InventoryExpirationBalance), permanently mismatching against the total and
        # tripping EXPIRATION_COUNT_NEEDED on nearly every tracked item from day one.
        lots = {s: _ExpirationLots([[window_start + timedelta(days=_shelf_life_days(rng)), profile.max_quantity]]) for s in storages}
    else:
        lots = None
    prev_t = datetime.combine(window_start, time(0))

    for idx, t in enumerate(session_times):
        # The very first checkpoint IS the item's genesis -- nothing existed to
        # take out before it, so there's no prior elapsed period to generate
        # usage for (the max(...,1) floor below exists for every later gap,
        # where real time has actually passed).
        elapsed_days = 0 if idx == 0 else max((t - prev_t).days, 1)
        year_mult = ref.catalog.year_multiplier(t.year)
        sev = PlannedEvent(ts=t, kind="bulk_session")
        for s in storages:
            expected_scans = profile.takeout.scans_per_day * location_multiplier * year_mult * elapsed_days / n_storages
            n_scans = int(rng.poisson(max(expected_scans, 0.0)))
            # Scans must be processed in the order they'll actually appear on the
            # timeline -- a real person can't take out more than what's physically
            # left. Drawing quantities before ordering (as before) let a burst of
            # scans between two checkpoints sum past the starting balance, which
            # the app's own trend chart correctly reconstructs as a transient dip
            # below zero. Pick days first, sort, THEN draw each qty against
            # whatever remains at that point in the sequence. Never land ON
            # prev_t's own calendar day -- a scan there could get a random
            # time-of-day earlier than prev_t's own checkpoint timestamp and
            # sort before it, implying a takeout before that count ever happened.
            scan_days = sorted(prev_t.date() + timedelta(days=int(rng.integers(1, elapsed_days + 1))) for _ in range(n_scans))
            remaining = balances[s]
            for scan_day in scan_days:
                if remaining <= 0.05:
                    break
                available_before = remaining
                true_qty = min(_lognormal_from_mean(rng, profile.takeout.qty_mean, profile.takeout.qty_sigma), remaining)
                remaining -= true_qty
                is_admin_actor = rng.random() < cfg.ADMIN_TAKEOUT_TRANSFER_RATE
                # over-report noise (~1%) can log MORE than the true amount taken --
                # someone can still only physically log what was on the shelf, so
                # cap the logged amount at what was actually there before this scan.
                logged_qty = _apply_scan_compliance(rng, true_qty)
                if logged_qty is not None:
                    logged_qty = min(logged_qty, max(round(available_before), 1))
                # allocation must sum to the LOGGED quantity (what the action records),
                # not the true physical quantity -- they diverge whenever compliance
                # noise under/over-reports, and the real app requires an exact match.
                allocations = lots[s].take(rng, logged_qty, profile.expiration) if lots and logged_qty else []
                if logged_qty is None:
                    continue
                ts = _sample_timestamp_for_day(rng, scan_day, ref)
                events.append(PlannedEvent(
                    ts=ts, kind="scan", item_name=item_name, operation_type="TAKEOUT",
                    quantity=logged_qty, from_storage=s, to_storage=None, admin_action=is_admin_actor,
                    expiration_allocations=allocations or None,
                ))
            balances[s] = max(0.0, remaining)

            raw = balances[s] * float(rng.lognormal(0, cfg.AUDIT_COUNT_NOISE_SIGMA))
            observed = max(0, round(min(raw, profile.max_quantity)))
            sev.counts[(item_name, s)] = observed
            balances[s] = float(observed)
            expiring_soon = False
            if lots:
                # Every COUNT of a tracked item needs an allocation too (same real
                # rule as TAKEOUT/TRANSFER/RESTOCK) -- reconcile the internal lot
                # ledger against what was actually counted.
                sev.count_expirations[s] = lots[s].reconcile(observed)

                # A well-run squad pulls actually-expired stock off the shelf
                # (discarded, not left sitting there inflating the count) --
                # logged as a separate takeout right after the count that found it,
                # not merged into the count itself.
                for lot in [lot for lot in lots[s].lots if lot[0] < t.date()]:
                    if rng.random() >= cfg.EXPIRATION_DISCARD_PROBABILITY:
                        continue
                    expires_on, discard_qty = lot
                    lots[s].lots.remove(lot)
                    balances[s] = max(0.0, balances[s] - discard_qty)
                    events.append(PlannedEvent(
                        ts=t + timedelta(minutes=int(rng.integers(5, 120))),
                        kind="scan", item_name=item_name, operation_type="TAKEOUT",
                        quantity=discard_qty, from_storage=s, to_storage=None, admin_action=True,
                        expiration_allocations=[(expires_on, discard_qty)],
                    ))
                # Get ahead of anything still on the shelf that's expiring soon --
                # reorder it now, independent of whether the item is otherwise low.
                soon_cutoff = t.date() + timedelta(days=cfg.EXPIRATION_SOON_DAYS)
                expiring_soon = any(lot[0] <= soon_cutoff for lot in lots[s].lots) and rng.random() < cfg.EXPIRATION_PROACTIVE_RESTOCK_PROBABILITY

            trigger = max(1.0, rng.normal(
                profile.min_quantity * profile.reorder_trigger.center_ratio,
                max(profile.min_quantity * profile.reorder_trigger.spread_ratio, 0.1),
            ))
            if expiring_soon or (observed <= trigger and rng.random() < cfg.RESTOCK_ACTION_PROBABILITY):
                # balances[s] reflects any discard above; observed alone would be
                # stale (it's what was counted BEFORE expired stock got pulled).
                restock_qty = int(np.ceil(max(profile.max_quantity - balances[s], 0) / profile.batch_size)) * profile.batch_size
                if restock_qty > 0:
                    sev.restocks[(item_name, s)] = restock_qty
                    balances[s] += restock_qty
                    if lots:
                        # admin estimates a smart expiration date from the order date, not a random horizon
                        expires_on = t.date() + timedelta(days=_shelf_life_days(rng))
                        lots[s].add(expires_on, restock_qty)
                        # This must also be attached to the RESTOCK action itself, not just
                        # tracked internally -- otherwise no real InventoryExpirationBalance
                        # row is ever created, and EXPIRED_STOCK/EXPIRING_SOON alerts (and the
                        # whole point of tracking expiration) can never fire on anything.
                        sev.restock_expirations[s] = [(expires_on, restock_qty)]
        events.append(sev)
        prev_t = t

    # Start no earlier than the day after the first real COUNT -- a transfer out
    # of a storage that hasn't been established yet has the same "activity
    # before anything was ever counted in" problem as an early takeout.
    transfer_start = (session_times[0].date() + timedelta(days=1)) if session_times else window_start
    events += _plan_transfer_stream(item_name, profile, transfer_start, window_end, location_multiplier, storages, rng, ref, expiration_tracked)
    return events


def _plan_transfer_stream(
    item_name: str,
    profile: ItemGenerationProfile,
    window_start: date,
    window_end: date,
    location_multiplier: float,
    storages: list[str],
    rng: np.random.Generator,
    ref: RefData,
    expiration_tracked: bool,
) -> list[PlannedEvent]:
    """Transfers move stock between storages -- a light, independent stream;
    they don't consume stock so they sit outside the usage/floor/restock loop."""
    if len(storages) < 2:
        return []
    transfer_rate_per_day = profile.takeout.scans_per_day * cfg.TRANSFER_SHARE_OF_TAKEOUT
    active_days = max((window_end - window_start).days, 1)
    day_range = [window_start + timedelta(days=i) for i in range(active_days)]
    # Apply the same real year-over-year trend TAKEOUT uses -- otherwise transfers
    # stay flat across a year (e.g. 2024) that every other op type shows a real dip in.
    year_mults = np.array([ref.catalog.year_multiplier(d.year) for d in day_range])
    expected_events = transfer_rate_per_day * location_multiplier * year_mults.sum()
    n_events = int(rng.poisson(max(expected_events, 0.0)))
    if n_events == 0:
        return []
    weights = np.array([_day_weight(d, ref) for d in day_range]) * year_mults
    if weights.sum() <= 0:
        return []
    days = _sample_days(rng, day_range, weights, n_events)
    events: list[PlannedEvent] = []
    for d in days:
        # This stream doesn't track a live per-storage balance (unlike the main
        # takeout loop), so cap at min_quantity as a rough "typical low-end stock"
        # ceiling -- keeps an occasional large draw from transferring out more
        # than a low-stock item plausibly has on hand.
        qty = max(1, min(round(_lognormal_from_mean(rng, profile.takeout.qty_mean, profile.takeout.qty_sigma)), profile.min_quantity))
        src, dst = rng.choice(storages, size=2, replace=False)
        is_admin_actor = rng.random() < cfg.ADMIN_TAKEOUT_TRANSFER_RATE
        ts = _sample_timestamp_for_day(rng, d, ref)
        # Real validation requires an allocation covering the full quantity whenever
        # the item is expiration-tracked, for every op type including TRANSFER --
        # no per-lot tracking on this stream, so log it as unspecified-date.
        allocations = [(None, qty)] if expiration_tracked else None
        events.append(PlannedEvent(
            ts=ts, kind="scan", item_name=item_name, operation_type="TRANSFER",
            quantity=qty, from_storage=str(src), to_storage=str(dst), admin_action=is_admin_actor,
            expiration_allocations=allocations,
        ))
    return events


# ---------------------------------------------------------------- unknown UPC stream
def plan_unknown_upc_stream(window_start: date, window_end: date, ref: RefData, rng: np.random.Generator) -> list[PlannedEvent]:
    events: list[PlannedEvent] = []
    span_days = (window_end - window_start).days
    for seed in cfg.UNKNOWN_UPC_SEED:
        offset = int(rng.integers(0, max(span_days, 1)))
        scan_day = window_start + timedelta(days=offset)
        scan_ts = _sample_timestamp_for_day(rng, scan_day, ref)
        events.append(PlannedEvent(ts=scan_ts, kind="unknown_upc_scan", upc=seed["upc"], resolve_to_item_name=seed["resolve_to_item_name"]))
        if rng.random() < cfg.UNKNOWN_UPC_RESOLVE_RATE:
            resolve_ts = scan_ts + timedelta(days=int(rng.integers(1, 30)))
            if resolve_ts.date() <= window_end:
                events.append(
                    PlannedEvent(ts=resolve_ts, kind="unknown_upc_resolve", upc=seed["upc"], resolve_to_item_name=seed["resolve_to_item_name"])
                )
    return events


# ---------------------------------------------------------------- error/correction injection
def inject_errors(events: list[PlannedEvent], rng: np.random.Generator, disabled_features: frozenset[str] = frozenset()) -> list[PlannedEvent]:
    tracked_names = cfg.EXPIRATION_TRACKED_ITEM_NAMES if "expiration" not in disabled_features else frozenset()
    extra: list[PlannedEvent] = []
    for ev in events:
        if ev.kind != "scan":
            continue
        if rng.random() < cfg.RAPID_DOUBLE_SCAN_RATE:
            dup = replace(ev, ts=ev.ts + timedelta(seconds=int(rng.integers(1, 6))))
            extra.append(dup)
        if ev.operation_type == "TAKEOUT" and rng.random() < cfg.WRONG_OP_THEN_FIXED_RATE:
            fixup_ts = ev.ts + timedelta(seconds=int(rng.integers(10, 600)))
            # Real validation requires a full-quantity allocation whenever the item
            # is expiration-tracked, for every op type -- no lot ledger reachable
            # here, so log it as unspecified-date.
            allocations = [(None, ev.quantity)] if ev.item_name in tracked_names else None
            fixup = PlannedEvent(
                ts=fixup_ts,
                kind="scan", item_name=ev.item_name, operation_type="RESTOCK",
                quantity=ev.quantity, from_storage=None, to_storage=ev.from_storage, admin_action=True,
                expiration_allocations=allocations,
            )
            extra.append(fixup)
    return events + extra


# ---------------------------------------------------------------- top-level
def _clamp_negative_dips(events: list[PlannedEvent]) -> list[PlannedEvent]:
    """Final safety net over the fully-assembled, time-sorted timeline. The main
    generation loop bounds itself against the running balance, but rapid-double-
    scan duplicates and the independent transfer stream don't share that state,
    so a TAKEOUT/TRANSFER from either can still land when the real physical
    balance is already too low. Walk the real timeline and clamp any such event
    to what's actually left -- guarantees "never draws past zero" unconditionally,
    regardless of which mechanism produced the event."""
    balances: dict[tuple[str, str], float] = {}
    kept: list[PlannedEvent] = []
    for e in events:
        if e.kind == "bulk_session":
            for key, qty in e.counts.items():
                balances[key] = float(qty)
            for key, qty in e.restocks.items():
                balances[key] = balances.get(key, 0.0) + qty
            kept.append(e)
            continue
        if e.kind == "scan" and e.operation_type in ("TAKEOUT", "TRANSFER"):
            key = (e.item_name, e.from_storage)
            available = balances.setdefault(key, float(e.quantity))
            if e.quantity > available:
                e.quantity = max(int(round(available)), 0)
                if e.quantity <= 0:
                    continue  # nothing physically left to take/move -- drop the event
                if e.expiration_allocations:
                    e.expiration_allocations = [(None, e.quantity)]
            balances[key] -= e.quantity
            if e.operation_type == "TRANSFER":
                dst = (e.item_name, e.to_storage)
                balances[dst] = balances.get(dst, 0.0) + e.quantity
        kept.append(e)
    return kept


def build_location_plan(
    location_name: str,
    location_multiplier: float,
    storages: list[str],
    catalog: CatalogProfiles,
    ref: RefData,
    seed: int,
    disabled_features: frozenset[str] = frozenset(),
) -> list[PlannedEvent]:
    rng = np.random.default_rng(seed)
    window_end = cfg.GENERATION_END_DATE
    window_start = window_end - timedelta(days=cfg.YEARS_BACK * 365)

    events: list[PlannedEvent] = []
    for name, profile in catalog.items.items():
        events.extend(build_item_events(name, profile, storages, location_multiplier, rng, ref, window_start, window_end, disabled_features))

    events = inject_errors(events, rng, disabled_features)
    events.sort(key=lambda e: e.ts)
    events = _clamp_negative_dips(events)
    return events


def build_unknown_upc_plan(ref: RefData, seed: int) -> list[PlannedEvent]:
    rng = np.random.default_rng(seed)
    window_end = cfg.GENERATION_END_DATE
    window_start = window_end - timedelta(days=cfg.YEARS_BACK * 365)
    events = plan_unknown_upc_stream(window_start, window_end, ref, rng)
    events.sort(key=lambda e: e.ts)
    return events
