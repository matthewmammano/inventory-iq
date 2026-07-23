"""Alert lifecycle: open, supersede, and resolve alerts from scans and audits.

One reconcile rule drives every condition-based alert (stock, stale, rare,
expiration): the set that *should* be open is computed from current state, then
compared to what *is* open -- a new key opens a row, a changed alert type closes
the old row (SUPERSEDED) and opens a new one, and a vanished key resolves its row.
Occurrence alerts (scan activity, unknown UPC) are opened directly and closed on
resolution or by an age sweep. Any new alert row starts with a clean notification
slate, which is what lets escalation and recurrence notify immediately.
"""

from collections.abc import Collection
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import Agency, Location, Storage
from app.inventory.item_queries import get_agency_item
from app.inventory.location_state_policy import evaluate_stock_state
from app.inventory.location_state_service import ItemLocationKey, affected_item_location_keys_for_actions, rebuild_item_location_states
from app.inventory.models import ActionLog, InventoryItemLocationState, Item
from app.shared.clock import utc_now_naive

from .audit_queries import (
    ExpirationAuditRow,
    ExpirationCountAuditRow,
    StateAuditRow,
    latest_prior_takeout_at,
    load_expiration_audit_rows,
    load_expiration_count_audit_rows,
    load_state_audit_rows,
)
from .constants import ACTION_ALERT_TYPES, STOCK_ALERT_TYPES, AlertStatus, AlertType, ClosedReason
from .models import Alert
from .payloads import (
    ExpirationCountNeededPayload,
    ExpirationStockPayload,
    RareTakeoutPayload,
    ScanActivityPayload,
    StaleCountPayload,
    UnknownUpcPayload,
)

STALE_TYPES = (AlertType.STALE_COUNT,)
EXPIRATION_TYPES = (AlertType.EXPIRED_STOCK, AlertType.EXPIRING_SOON, AlertType.EXPIRATION_COUNT_NEEDED)
INFORMATIONAL_SWEEP_AGE = timedelta(days=2)
# No takeout ever recorded for this item/location, but the account itself is at least this old.
RARE_TAKEOUT_NO_PRIOR_ACCOUNT_AGE_DAYS = 365

AlertKey = tuple[int, str]  # (agency_id, dedupe_key)


@dataclass(frozen=True)
class AlertSpec:
    """The alert that should currently be open for one (agency, dedupe key)."""

    agency_id: int
    dedupe_key: str
    alert_type: AlertType
    item_id: int | None
    agency_location_id: int | None
    detail: dict[str, Any]

    @property
    def key(self) -> AlertKey:
        return (self.agency_id, self.dedupe_key)


# --------------------------------------------------------------------------- #
# Public entry points
# --------------------------------------------------------------------------- #


def record_action_log_alerts(session: Session, action_logs: list[ActionLog]) -> None:
    """Open scan-activity and rare-takeout alerts, and refresh stock/stale alerts for affected items."""
    if not action_logs:
        return

    now = _now()
    for action in action_logs:
        _open_scan_activity_alert(session, action, now)
        _open_rare_takeout_alert(session, action, now)

    keys = affected_item_location_keys_for_actions(session, action_logs)
    stock_count = sync_stock_alerts(session, item_location_keys=keys, now=now)
    audit_count = sync_state_audit_alerts(session, item_location_keys=keys, now=now)
    logger.info(
        "Inventory action alerts refreshed",
        extra={"action_count": len(action_logs), "affected_item_location_count": len(keys), "stock_alerts": stock_count, "audit_alerts": audit_count},
    )


def generate_scheduled_alerts(session: Session, agency_id: int | None = None) -> int:
    """Run the full safety audit: rebuild state, then reconcile every alert category."""
    now = _now()
    state_count = rebuild_item_location_states(session, agency_id)
    stock_count = sync_stock_alerts(session, agency_id=agency_id, now=now)
    audit_count = sync_state_audit_alerts(session, agency_id=agency_id, now=now)
    expiration_count = sync_expiration_alerts(session, agency_id=agency_id, now=now)
    swept = _sweep_informational_alerts(session, agency_id, now)
    logger.info(
        "Inventory alert safety audit finished",
        extra={
            "agency_id": agency_id,
            "state_rows_checked": state_count,
            "stock_alerts": stock_count,
            "audit_alerts": audit_count,
            "expiration_alerts": expiration_count,
            "informational_swept": swept,
        },
    )
    return state_count


def sync_stock_alerts(
    session: Session,
    *,
    agency_id: int | None = None,
    item_location_keys: set[ItemLocationKey] | None = None,
    now: datetime | None = None,
) -> int:
    """Reconcile stock/forecast alerts from current item/location state (rendered live)."""
    if item_location_keys is not None and not item_location_keys:
        return 0
    now = now or _now()
    desired = _desired_stock_alerts(session, agency_id, item_location_keys)
    open_now = _open_alerts(session, agency_id, STOCK_ALERT_TYPES, item_location_keys)
    _reconcile(session, desired, open_now, now)
    return len(desired)


def sync_state_audit_alerts(
    session: Session,
    *,
    agency_id: int | None = None,
    item_location_keys: set[ItemLocationKey] | None = None,
    now: datetime | None = None,
) -> int:
    """Reconcile stale-count alerts from current item/location state."""
    if item_location_keys is not None and not item_location_keys:
        return 0
    now = now or _now()
    desired: dict[AlertKey, AlertSpec] = {}
    for row in load_state_audit_rows(session, agency_id, item_location_keys):
        _add_stale_count_spec(desired, row, now)
    open_now = _open_alerts(session, agency_id, STALE_TYPES, item_location_keys)
    _reconcile(session, desired, open_now, now)
    return len(desired)


def sync_expiration_alerts(session: Session, *, agency_id: int | None = None, now: datetime | None = None) -> int:
    """Reconcile expiration alerts from current tracked expiration balances (full agency)."""
    now = now or _now()
    today = now.date()
    desired: dict[AlertKey, AlertSpec] = {}
    for row in load_expiration_audit_rows(session, agency_id):
        _add_expiration_stock_spec(desired, row, today)
    for count_row in load_expiration_count_audit_rows(session, agency_id):
        _add_expiration_count_spec(desired, count_row)
    open_now = _open_alerts(session, agency_id, EXPIRATION_TYPES, None)
    _reconcile(session, desired, open_now, now)
    return len(desired)


def open_unknown_upc_alert(
    session: Session,
    agency_id: int,
    *,
    unknown_upc_id: int,
    upc: str,
    lookup_title: str | None,
    created_at: datetime,
) -> Alert:
    """Open (or refresh) the alert for one unresolved unknown UPC."""
    detail = UnknownUpcPayload(unknown_upc_id=unknown_upc_id, upc=upc, lookup_title=lookup_title, created_at=created_at).as_json()
    spec = AlertSpec(agency_id, f"UPC:{unknown_upc_id}", AlertType.UNKNOWN_UPC, None, None, detail)
    return _open_or_refresh(session, spec, _now())


def resolve_unknown_upc_alert(session: Session, agency_id: int, upc: str) -> None:
    """Resolve open unknown-UPC alerts for one UPC (it was assigned or dismissed)."""
    now = _now()
    for alert in _open_alerts(session, agency_id, (AlertType.UNKNOWN_UPC,), None).values():
        if alert.detail.get("upc") == upc:
            _close_alert(alert, now, ClosedReason.RESOLVED)


# --------------------------------------------------------------------------- #
# Reconcile core
# --------------------------------------------------------------------------- #


def _reconcile(session: Session, desired: dict[AlertKey, AlertSpec], open_now: dict[AlertKey, Alert], now: datetime) -> None:
    for cache_key, spec in desired.items():
        existing = open_now.get(cache_key)
        if existing is None:
            _insert_alert(session, spec, now)
        elif existing.alert_type != spec.alert_type:
            _close_alert(existing, now, ClosedReason.SUPERSEDED)
            session.flush()  # release the partial-unique open key before reinserting it
            _insert_alert(session, spec, now)
        elif existing.detail != spec.detail:
            existing.detail = spec.detail
    for cache_key, existing in open_now.items():
        if cache_key not in desired:
            _close_alert(existing, now, ClosedReason.RESOLVED)
    session.flush()


def _open_or_refresh(session: Session, spec: AlertSpec, now: datetime) -> Alert:
    existing = session.scalar(
        select(Alert).where(Alert.agency_id == spec.agency_id, Alert.dedupe_key == spec.dedupe_key, Alert.status == AlertStatus.OPEN)
    )
    if existing is None:
        return _insert_alert(session, spec, now)
    if existing.alert_type != spec.alert_type:
        _close_alert(existing, now, ClosedReason.SUPERSEDED)
        session.flush()
        return _insert_alert(session, spec, now)
    if existing.detail != spec.detail:
        existing.detail = spec.detail
    return existing


def _insert_alert(session: Session, spec: AlertSpec, now: datetime) -> Alert:
    alert = Alert(
        agency_id=spec.agency_id,
        alert_type=spec.alert_type,
        item_id=spec.item_id,
        agency_location_id=spec.agency_location_id,
        status=AlertStatus.OPEN,
        dedupe_key=spec.dedupe_key,
        detail=spec.detail,
        opened_at=now,
    )
    session.add(alert)
    return alert


def _close_alert(alert: Alert, now: datetime, reason: ClosedReason) -> None:
    alert.status = AlertStatus.CLOSED
    alert.closed_reason = reason
    alert.closed_at = now


def _open_alerts(
    session: Session,
    agency_id: int | None,
    alert_types: Collection[AlertType],
    item_location_keys: set[ItemLocationKey] | None,
) -> dict[AlertKey, Alert]:
    stmt = select(Alert).where(Alert.status == AlertStatus.OPEN, Alert.alert_type.in_(alert_types))
    if agency_id is not None:
        stmt = stmt.where(Alert.agency_id == agency_id)
    result: dict[AlertKey, Alert] = {}
    for alert in session.execute(stmt).scalars():
        if item_location_keys is not None and _alert_item_location_key(alert) not in item_location_keys:
            continue
        result[(alert.agency_id, alert.dedupe_key)] = alert
    return result


def _sweep_informational_alerts(session: Session, agency_id: int | None, now: datetime) -> int:
    cutoff = now - INFORMATIONAL_SWEEP_AGE
    swept = 0
    for alert in _open_alerts(session, agency_id, ACTION_ALERT_TYPES.values(), None).values():
        if alert.opened_at < cutoff:
            _close_alert(alert, now, ClosedReason.SENT)
            swept += 1
    if swept:
        session.flush()
    return swept


def _alert_item_location_key(alert: Alert) -> ItemLocationKey | None:
    if alert.item_id is None or alert.agency_location_id is None:
        return None
    return ItemLocationKey(alert.agency_id, alert.item_id, alert.agency_location_id)


# --------------------------------------------------------------------------- #
# Desired-alert builders
# --------------------------------------------------------------------------- #


def _desired_stock_alerts(
    session: Session,
    agency_id: int | None,
    item_location_keys: set[ItemLocationKey] | None,
) -> dict[AlertKey, AlertSpec]:
    stmt = (
        select(InventoryItemLocationState, Item.prior_daily_usage)
        .join(Item, Item.id == InventoryItemLocationState.item_id)
        .where(InventoryItemLocationState.last_counted_at.is_not(None))
    )
    if agency_id is not None:
        stmt = stmt.where(InventoryItemLocationState.agency_id == agency_id)

    desired: dict[AlertKey, AlertSpec] = {}
    for state, prior_daily_usage in session.execute(stmt).all():
        key = ItemLocationKey(state.agency_id, state.item_id, state.agency_location_id)
        if item_location_keys is not None and key not in item_location_keys:
            continue
        alert_type = evaluate_stock_state(
            total_quantity=state.total_quantity,
            min_quantity=state.min_quantity_snapshot,
            lead_time_days=state.lead_time_days_snapshot,
            prior_daily_usage=float(prior_daily_usage or 0),
            trend_per_day=state.trend_per_day,
        ).effective_alert_type
        if alert_type is None:
            continue
        spec = AlertSpec(
            state.agency_id, f"STOCK:{state.item_id}:{state.agency_location_id}", alert_type, state.item_id, state.agency_location_id, {}
        )
        desired[spec.key] = spec
    return desired


def _add_stale_count_spec(desired: dict[AlertKey, AlertSpec], row: StateAuditRow, now: datetime) -> None:
    days = int(row.count_last_days or 0)
    if days <= 0:
        return
    days_since = _days_since_current_date(now, row.last_counted_at)
    if days_since is not None and days_since < days:
        return
    detail = StaleCountPayload(
        item_id=row.item_id,
        item_name=row.item_name,
        agency_location_id=row.location_id,
        location_name=row.location_name,
        days_since_last_count=days_since,
        current_total=row.total_quantity,
        last_counted_at=row.last_counted_at,
    ).as_json()
    stamp = _iso(row.last_counted_at) or "NEVER"
    spec = AlertSpec(row.agency_id, f"STALE:{row.item_id}:{row.location_id}:{stamp}", AlertType.STALE_COUNT, row.item_id, row.location_id, detail)
    desired[spec.key] = spec


def _add_expiration_stock_spec(desired: dict[AlertKey, AlertSpec], row: ExpirationAuditRow, today: date) -> None:
    days_until = (row.expires_on - today).days
    if days_until < 0:
        alert_type = AlertType.EXPIRED_STOCK
    elif days_until <= row.notice_days:
        alert_type = AlertType.EXPIRING_SOON
    else:
        return
    detail = ExpirationStockPayload(
        item_id=row.item_id,
        item_name=row.item_name,
        storage_id=row.storage_id,
        storage_name=row.storage_name,
        agency_location_id=row.location_id,
        location_name=row.location_name,
        expires_on=row.expires_on,
        quantity=row.quantity,
        days_until_expiration=days_until,
        notice_days=row.notice_days,
    ).as_json()
    spec = AlertSpec(
        row.agency_id, f"EXP:{row.item_id}:{row.storage_id}:{row.expires_on.isoformat()}", alert_type, row.item_id, row.location_id, detail
    )
    desired[spec.key] = spec


def _add_expiration_count_spec(desired: dict[AlertKey, AlertSpec], row: ExpirationCountAuditRow) -> None:
    difference = row.storage_quantity - row.tracked_expiration_quantity
    if difference == 0:
        return
    detail = ExpirationCountNeededPayload(
        item_id=row.item_id,
        item_name=row.item_name,
        storage_id=row.storage_id,
        storage_name=row.storage_name,
        agency_location_id=row.location_id,
        location_name=row.location_name,
        storage_quantity=row.storage_quantity,
        tracked_expiration_quantity=row.tracked_expiration_quantity,
        difference=difference,
    ).as_json()
    spec = AlertSpec(
        row.agency_id, f"EXPCOUNT:{row.item_id}:{row.storage_id}", AlertType.EXPIRATION_COUNT_NEEDED, row.item_id, row.location_id, detail
    )
    desired[spec.key] = spec


def _open_scan_activity_alert(session: Session, action_log: ActionLog, now: datetime) -> None:
    alert_type = ACTION_ALERT_TYPES.get(action_log.operation_type)
    if alert_type is None or action_log.item_id is None:
        return
    item = _load_action_item(session, action_log)
    if item is None:
        return
    from_location_id = _storage_location_id(session, action_log.agency_id, action_log.from_storage_id)
    to_location_id = _storage_location_id(session, action_log.agency_id, action_log.to_storage_id)
    detail = ScanActivityPayload(
        action_log_id=action_log.id,
        item_id=item.id,
        item_name=item.name,
        operation_type=action_log.operation_type,
        quantity=action_log.quantity,
        admin_action=bool(action_log.admin_action),
        from_agency_location_id=from_location_id,
        to_agency_location_id=to_location_id,
        from_location_name=_storage_history_name(session, action_log.agency_id, action_log.from_storage_id),
        to_location_name=_storage_history_name(session, action_log.agency_id, action_log.to_storage_id),
        time_scanned=action_log.time_scanned,
        item_alert_flagged=bool(item.scan_alert_flagged),
    ).as_json()
    spec = AlertSpec(action_log.agency_id, f"ACTION:{action_log.id}", alert_type, item.id, to_location_id or from_location_id, detail)
    _open_or_refresh(session, spec, now)


def _open_rare_takeout_alert(session: Session, action_log: ActionLog, now: datetime) -> None:
    """Open a rare-takeout alert if this scan just broke a long silence for this item/location.

    Fires when either the gap since the item/location's previous takeout, or -- if it has
    never been taken out before -- the agency's account age, clears the configured threshold.
    """
    if not action_log.is_takeout or action_log.item_id is None or action_log.from_storage_id is None:
        return
    item = _load_action_item(session, action_log)
    if item is None:
        return
    location_id = _storage_location_id(session, action_log.agency_id, action_log.from_storage_id)
    if location_id is None:
        return
    agency = session.get(Agency, action_log.agency_id)
    threshold_days = int(agency.alert_rare_scan_days or 0) if agency else 0
    if agency is None or threshold_days <= 0:
        return

    scanned_at = action_log.time_scanned or now
    previous_takeout_at = latest_prior_takeout_at(session, action_log.agency_id, item.id, location_id, before_action_id=action_log.id)
    days_since = _days_since_current_date(scanned_at, previous_takeout_at)
    if previous_takeout_at is not None:
        if days_since is None or days_since < threshold_days:
            return
    elif (scanned_at.date() - agency.created_at.date()).days < RARE_TAKEOUT_NO_PRIOR_ACCOUNT_AGE_DAYS:
        return

    detail = RareTakeoutPayload(
        item_id=item.id,
        item_name=item.name,
        agency_location_id=location_id,
        location_name=_location_name(session, action_log.agency_id, location_id),
        days_since_last_takeout=days_since,
        last_takeout_at=previous_takeout_at,
        current_total=_state_total_quantity(session, action_log.agency_id, item.id, location_id),
        rare_scan_days=threshold_days,
    ).as_json()
    spec = AlertSpec(action_log.agency_id, f"RARE:{action_log.id}", AlertType.RARE_TAKEOUT, item.id, location_id, detail)
    _open_or_refresh(session, spec, now)


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #


def _load_action_item(session: Session, action_log: ActionLog) -> Item | None:
    if action_log.item and action_log.item.agency_id == action_log.agency_id and action_log.item.active:
        return action_log.item
    if action_log.item_id is None:
        return None
    return get_agency_item(action_log.agency_id, action_log.item_id, session=session)


def _storage_history_name(session: Session, agency_id: int, storage_id: int | None) -> str | None:
    storage = _storage_row(session, agency_id, storage_id)
    return storage.history_name if storage and storage.agency_id == agency_id else None


def _storage_location_id(session: Session, agency_id: int, storage_id: int | None) -> int | None:
    storage = _storage_row(session, agency_id, storage_id)
    return storage.location_id if storage and storage.agency_id == agency_id else None


def _storage_row(session: Session, agency_id: int, storage_id: int | None) -> Storage | None:
    if storage_id is None:
        return None
    storage = session.get(Storage, storage_id)
    return storage if storage and storage.agency_id == agency_id else None


def _location_name(session: Session, agency_id: int, location_id: int) -> str:
    location = session.get(Location, location_id)
    return location.name if location and location.agency_id == agency_id else str(location_id)


def _state_total_quantity(session: Session, agency_id: int, item_id: int, location_id: int) -> int:
    total = session.scalar(
        select(InventoryItemLocationState.total_quantity).where(
            InventoryItemLocationState.agency_id == agency_id,
            InventoryItemLocationState.item_id == item_id,
            InventoryItemLocationState.agency_location_id == location_id,
        )
    )
    return int(total or 0)


def _days_since_current_date(now: datetime, observed_at: datetime | None) -> int | None:
    if observed_at is None:
        return None
    return (now.date() - observed_at.date()).days


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _now() -> datetime:
    return utc_now_naive()
