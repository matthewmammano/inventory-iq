"""Replay a PlannedEvent list through the real app service layer.

Every mutation goes through the same functions the live app calls (mutation_service
.inventory_operation, bulk_edit_service.save_bulk_edit, upc_service.*) -- real
guard logic runs, and can reject an event, exactly as it would for a live user.
Rejections are caught, logged, and skipped rather than bypassed.

Historical timestamps are achieved via the app's own built-in dev clock
(app/shared/clock.py, dev_clock.json) -- every utc_now()/utc_now_naive() call
anywhere in the app respects it, so real "requires a fresh count" / "is this
stale" checks evaluate correctly against simulated time, not wall-clock time.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session
from tqdm import tqdm

from app.alerts.alert_service import generate_scheduled_alerts
from app.inventory.balance_service import rebuild_inventory_balances
from app.prediction.retraining_service import retrain_agency_trends
from app.inventory.bulk_edit_service import save_bulk_edit
from app.inventory.constants import OperationType
from app.inventory.expiration_service import ExpirationAllocation
from app.inventory.models import Item, UnknownUpcScan
from app.inventory.mutation_service import inventory_operation
from app.inventory.upc_service import record_unknown_upc, resolve_unknown_upc

import config as cfg
from app.shared.clock import CLOCK_FILE
from app.shared.config import settings

from planner import PlannedEvent
from setup import LocationRig, SetupResult


@dataclass(slots=True)
class ReplayStats:
    applied: int = 0
    skipped: int = 0
    skip_counts: dict[str, int] | None = None
    skip_examples: dict[str, str] | None = None

    def record_skip(self, key: str, message: str) -> None:
        self.skip_counts = self.skip_counts or {}
        self.skip_examples = self.skip_examples or {}
        self.skip_counts[key] = self.skip_counts.get(key, 0) + 1
        self.skip_examples.setdefault(key, message)
        self.skipped += 1


def set_fake_now(ts: datetime) -> None:
    if not settings.dev_clock_enabled:
        raise RuntimeError("DEV_CLOCK_ENABLED must be true to replay historical events")
    CLOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    CLOCK_FILE.write_text(json.dumps({"mode": "fixed", "fake_anchor": ts.replace(tzinfo=UTC).isoformat()}))


def clear_fake_clock() -> None:
    CLOCK_FILE.unlink(missing_ok=True)


def _progress(events: list[PlannedEvent], desc: str) -> tqdm:
    """miniters=2% of the stream, mininterval=0 -- refresh is driven by event count, not
    wall-clock time, so the bar visibly steps every 2% regardless of how slow replay is."""
    step = max(1, len(events) // 50)
    return tqdm(events, desc=desc, miniters=step, mininterval=0, dynamic_ncols=True, unit="ev")


def replay_location(db: Session, agency_id: int, rig: LocationRig, items_by_name: dict[str, Item], events: list[PlannedEvent]) -> ReplayStats:
    storage_id_by_name = {name: storage.id for name, storage in rig.storages.items()}
    item_id_by_name = {name: item.id for name, item in items_by_name.items()}
    stats = ReplayStats()

    bar = _progress(events, rig.location.name)
    for ev in bar:
        set_fake_now(ev.ts)
        try:
            if ev.kind == "scan":
                _replay_scan(db, agency_id, ev, item_id_by_name, storage_id_by_name)
            elif ev.kind == "bulk_session":
                _replay_bulk_session(db, agency_id, rig.location.id, ev, item_id_by_name, storage_id_by_name)
            else:
                continue  # unknown_upc_* handled separately, agency-scoped not location-scoped
            db.commit()
            stats.applied += 1
        except Exception as exc:  # noqa: BLE001 -- intentionally broad: any rejection is a valid, loggable outcome
            db.rollback()
            stats.record_skip(f"{ev.kind}:{type(exc).__name__}", str(exc))
        bar.set_postfix(applied=stats.applied, skipped=stats.skipped)
    return stats


def replay_unknown_upcs(db: Session, agency_id: int, items_by_name: dict[str, Item], events: list[PlannedEvent]) -> ReplayStats:
    stats = ReplayStats()
    bar = _progress(events, "unknown-UPC")
    for ev in bar:
        set_fake_now(ev.ts)
        try:
            if ev.kind == "unknown_upc_scan":
                record_unknown_upc(db, agency_id, ev.upc)
            elif ev.kind == "unknown_upc_resolve":
                scan = db.scalar(select(UnknownUpcScan).where(UnknownUpcScan.agency_id == agency_id, UnknownUpcScan.upc == ev.upc))
                if scan is None:
                    raise ValueError("no pending unknown-UPC row to resolve")
                item = items_by_name[ev.resolve_to_item_name]
                resolve_unknown_upc(db, agency_id, scan.id, item.id)
            db.commit()
            stats.applied += 1
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            stats.record_skip(f"{ev.kind}:{type(exc).__name__}", str(exc))
        bar.set_postfix(applied=stats.applied, skipped=stats.skipped)
    return stats


def _replay_scan(
    db: Session,
    agency_id: int,
    ev: PlannedEvent,
    item_id_by_name: dict[str, int],
    storage_id_by_name: dict[str, int],
) -> None:
    op = OperationType(ev.operation_type)
    allocations = (
        [ExpirationAllocation(expires_on=exp, quantity=qty) for exp, qty in ev.expiration_allocations]
        if ev.expiration_allocations
        else None
    )
    inventory_operation(
        agency_id=agency_id,
        item_id=item_id_by_name[ev.item_name],
        quantity=ev.quantity,
        operation_type=op,
        from_storage=storage_id_by_name.get(ev.from_storage) if ev.from_storage else None,
        to_storage=storage_id_by_name.get(ev.to_storage) if ev.to_storage else None,
        admin_action=ev.admin_action,
        expiration_allocations=allocations,
        session=db,
    )


def _replay_bulk_session(
    db: Session,
    agency_id: int,
    location_id: int,
    ev: PlannedEvent,
    item_id_by_name: dict[str, int],
    storage_id_by_name: dict[str, int],
) -> None:
    counts = {
        (item_id_by_name[name], storage_id_by_name[storage]): qty
        for (name, storage), qty in ev.counts.items()
    }
    restocks = {
        (item_id_by_name[name], storage_id_by_name[storage]): qty
        for (name, storage), qty in ev.restocks.items()
    }
    # COUNT and RESTOCK of a tracked item both need an allocation attached --
    # the real app validates this for every op type, not just TAKEOUT/TRANSFER
    # (see planner.py build_item_events, sev.count_expirations/restock_expirations).
    # Every bulk_session PlannedEvent is single-item, so item_id is the same for
    # every entry here; COUNT always fires, so it's the reliable source for it.
    exp_by_key = {}
    if ev.count_expirations or ev.restock_expirations:
        item_id = next(iter(item_id_by_name[name] for name, _ in ev.counts))
        for op, expirations in (("count", ev.count_expirations), ("restock", ev.restock_expirations)):
            for storage, allocations in expirations.items():
                key = f"{op}_{item_id}_{storage_id_by_name[storage]}"
                exp_by_key[key] = [ExpirationAllocation(expires_on=exp, quantity=qty) for exp, qty in allocations]

    # Replayed separately with a staggered timestamp, not one save_bulk_edit(counts=, restocks=)
    # call: a real recount-then-restock visit takes time between the two, and giving them the
    # exact same timestamp makes their real order unrecoverable later.
    if counts:
        save_bulk_edit(db, agency_id=agency_id, agency_location_id=location_id, counts=counts, restocks={}, expiration_allocations_by_key=exp_by_key)
    if restocks:
        if counts:
            set_fake_now(ev.ts + timedelta(seconds=cfg.BULK_SESSION_RESTOCK_STAGGER_SECONDS))
        save_bulk_edit(db, agency_id=agency_id, agency_location_id=location_id, counts={}, restocks=restocks, expiration_allocations_by_key=exp_by_key)


def final_rebuild(db: Session, agency_id: int) -> None:
    """Recompute all derived state at real wall-clock now, matching a live deployment today."""
    clear_fake_clock()
    rebuild_inventory_balances(db, agency_id)
    db.commit()
    retrain_agency_trends(db, agency_id)  # fits trend_per_day/confidence/segment_count from COUNT history
    db.commit()  # session autoflush=False -- must land before rebuild_item_location_states queries state rows
    generate_scheduled_alerts(db, agency_id)  # rebuilds item/location states + reconciles all alert types
    db.commit()
