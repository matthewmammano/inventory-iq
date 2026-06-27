"""Discrete alert event generation and item/location state safety refresh."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import Agencies, AgencyLocations, AgencyStorages
from app.inventory.item_queries import get_agency_item
from app.inventory.location_state_service import affected_item_location_keys_for_actions, rebuild_item_location_states
from app.inventory.models import ActionLogs, InventoryItemLocationState, Items
from app.shared.clock import utc_now_naive

from .constants import ACTION_ALERT_TYPES, ALERT_DEFINITIONS, AlertSeverity, AlertSourceType, AlertType, InventoryAlertEventStatus
from .models import InventoryAlertEvent

OPEN_EVENT_STATUSES = (
    InventoryAlertEventStatus.PENDING,
    InventoryAlertEventStatus.NO_RECIPIENT,
    InventoryAlertEventStatus.QUEUED,
    InventoryAlertEventStatus.ERROR,
)
STATE_AUDIT_EVENT_TYPES = (AlertType.STALE_COUNT, AlertType.RARE_TAKEOUT)


@dataclass(frozen=True)
class StateAuditRow:
    """Flat state row used by the scheduled audit without ORM relationship traversal."""

    agency_id: int
    count_last_days: int
    alert_rare_scan_days: int
    item_id: int
    item_name: str
    location_id: int
    location_name: str
    total_quantity: int
    last_counted_at: datetime | None
    last_takeout_at: datetime | None


def record_action_log_alerts(
    session: Session,
    action_logs: list[ActionLogs],
) -> None:
    """Create discrete action events and refresh state-derived audit events."""
    if not action_logs:
        return

    now = _now()
    for action in action_logs:
        _record_scan_activity_event(session, action, now)

    affected_item_location_keys = affected_item_location_keys_for_actions(session, action_logs)
    state_event_count = sync_state_audit_events(session, item_location_keys=affected_item_location_keys, now=now)

    logger.info(
        "Inventory action alert state refreshed",
        extra={
            "action_count": len(action_logs),
            "affected_item_location_count": len(affected_item_location_keys),
            "state_event_count": state_event_count,
        },
    )


def generate_scheduled_alerts(session: Session, agency_id: int | None = None) -> int:
    """Run the inventory alert safety audit and refresh state-derived discrete alerts."""
    state_count = rebuild_item_location_states(session, agency_id)
    event_count = sync_state_audit_events(session, agency_id=agency_id)

    logger.info(
        "Inventory alert safety audit finished",
        extra={"agency_id": agency_id, "state_rows_checked": state_count, "event_checks": event_count},
    )
    return state_count + event_count


def sync_state_audit_events(
    session: Session,
    *,
    agency_id: int | None = None,
    item_location_keys: set[tuple[int, int, int]] | None = None,
    now: datetime | None = None,
) -> int:
    """Refresh stale-count and rare-takeout events from current item/location state."""
    if item_location_keys is not None and not item_location_keys:
        return 0

    now = now or _now()
    agencies = _active_agencies(session, agency_id)
    if agency_id is not None and not agencies:
        logger.warning(
            "State audit event refresh could not find an active agency for the requested id",
            extra={"agency_id": agency_id},
        )
        return 0

    _cancel_open_state_audit_events(session, agency_id=agency_id, item_location_keys=item_location_keys, now=now)
    state_audit_rows = _load_state_audit_rows(session, agency_id, item_location_keys)
    for state_audit_row in state_audit_rows:
        _sync_stale_count_state(session, state_audit_row, now)
        _sync_rare_takeout_state(session, state_audit_row, now)
    session.flush()
    return len(state_audit_rows)


def queue_unknown_upc_event(
    session: Session,
    agency_id: int,
    *,
    unknown_upc_id: int,
    upc: str,
    lookup_title: str | None,
    created_at: datetime,
) -> InventoryAlertEvent:
    """Create or refresh one pending unknown-UPC event."""
    return _upsert_event(
        session,
        agency_id=agency_id,
        alert_type=AlertType.UNKNOWN_UPC,
        severity=ALERT_DEFINITIONS[AlertType.UNKNOWN_UPC].severity,
        source_type=AlertSourceType.UNKNOWN_UPC_SCAN,
        source_id=unknown_upc_id,
        dedupe_key=f"UNKNOWN_UPC:{unknown_upc_id}",
        payload={
            "unknown_upc_id": unknown_upc_id,
            "upc": upc,
            "lookup_title": lookup_title,
            "created_at": created_at.isoformat(),
        },
        event_at=created_at,
        now=_now(),
    )


def cancel_unknown_upc_event(session: Session, agency_id: int, upc: str) -> None:
    """Cancel pending/queued unknown-UPC events for one UPC."""
    now = _now()
    events = session.execute(
        select(InventoryAlertEvent).where(
            InventoryAlertEvent.agency_id == agency_id,
            InventoryAlertEvent.alert_type == AlertType.UNKNOWN_UPC,
            InventoryAlertEvent.status.in_(OPEN_EVENT_STATUSES),
        )
    ).scalars()
    for event in events:
        if event.payload_json.get("upc") == upc:
            _cancel_event(event, now)


def _record_scan_activity_event(
    session: Session,
    action_log: ActionLogs,
    now: datetime,
) -> None:
    alert_type = ACTION_ALERT_TYPES.get(action_log.operation_type)
    if alert_type is None or action_log.item_id is None:
        return

    item = _load_action_item(session, action_log)
    if item is None:
        return

    payload = {
        "action_log_id": action_log.id,
        "item_id": item.id,
        "item_name": item.name,
        "operation_type": action_log.operation_type.value,
        "quantity": action_log.quantity_delta,
        "admin_action": bool(action_log.admin_action),
        "from_agency_location_id": _storage_location_id(session, action_log.agency_id, action_log.from_location_id),
        "to_agency_location_id": _storage_location_id(session, action_log.agency_id, action_log.to_location_id),
        "from_location_name": _storage_history_name(session, action_log.agency_id, action_log.from_location_id),
        "to_location_name": _storage_history_name(session, action_log.agency_id, action_log.to_location_id),
        "time_scanned": _iso(action_log.time_scanned),
    }
    _upsert_event(
        session,
        agency_id=action_log.agency_id,
        alert_type=alert_type,
        severity=AlertSeverity.INFO,
        source_type=AlertSourceType.ACTION_LOG,
        source_id=action_log.id,
        dedupe_key=f"ACTION_LOG:{action_log.id}",
        payload=payload,
        event_at=action_log.time_scanned or now,
        now=now,
    )


def _sync_stale_count_state(
    session: Session,
    state_audit_row: StateAuditRow,
    now: datetime,
) -> None:
    days = int(state_audit_row.count_last_days or 0)
    if days <= 0:
        return

    days_since = _days_since_current_date(now, state_audit_row.last_counted_at)
    if days_since is not None and days_since < days:
        return

    event_at = state_audit_row.last_counted_at or now
    _upsert_event(
        session,
        agency_id=state_audit_row.agency_id,
        alert_type=AlertType.STALE_COUNT,
        severity=ALERT_DEFINITIONS[AlertType.STALE_COUNT].severity,
        source_type=AlertSourceType.STALE_COUNT_AUDIT,
        source_id=None,
        dedupe_key=_stale_count_key(state_audit_row.item_id, state_audit_row.location_id, state_audit_row.last_counted_at),
        payload={
            "item_id": state_audit_row.item_id,
            "item_name": state_audit_row.item_name,
            "agency_location_id": state_audit_row.location_id,
            "location_name": state_audit_row.location_name,
            "days_since_last_count": days_since,
            "current_total": state_audit_row.total_quantity,
            "last_counted_at": _iso(state_audit_row.last_counted_at),
        },
        event_at=event_at,
        now=now,
    )


def _sync_rare_takeout_state(
    session: Session,
    state_audit_row: StateAuditRow,
    now: datetime,
) -> None:
    days = int(state_audit_row.alert_rare_scan_days or 0)
    if days <= 0 or state_audit_row.last_takeout_at is None:
        return

    days_since = _days_since_current_date(now, state_audit_row.last_takeout_at)
    if days_since is not None and days_since < days:
        return

    _upsert_event(
        session,
        agency_id=state_audit_row.agency_id,
        alert_type=AlertType.RARE_TAKEOUT,
        severity=ALERT_DEFINITIONS[AlertType.RARE_TAKEOUT].severity,
        source_type=AlertSourceType.RARE_TAKEOUT_AUDIT,
        source_id=None,
        dedupe_key=_rare_takeout_key(state_audit_row.item_id, state_audit_row.location_id, state_audit_row.last_takeout_at),
        payload={
            "item_id": state_audit_row.item_id,
            "item_name": state_audit_row.item_name,
            "agency_location_id": state_audit_row.location_id,
            "location_name": state_audit_row.location_name,
            "days_since_last_takeout": days_since,
            "last_takeout_at": _iso(state_audit_row.last_takeout_at),
            "current_total": state_audit_row.total_quantity,
            "rare_scan_days": days,
        },
        event_at=state_audit_row.last_takeout_at,
        now=now,
    )


def _upsert_event(
    session: Session,
    *,
    agency_id: int,
    alert_type: AlertType,
    severity: AlertSeverity,
    source_type: AlertSourceType,
    source_id: int | None,
    dedupe_key: str,
    payload: dict[str, Any],
    event_at: datetime,
    now: datetime,
) -> InventoryAlertEvent:
    existing = session.scalar(
        select(InventoryAlertEvent).where(
            InventoryAlertEvent.agency_id == agency_id,
            InventoryAlertEvent.dedupe_key == dedupe_key,
        )
    )
    if existing is None:
        event = InventoryAlertEvent(
            agency_id=agency_id,
            alert_type=alert_type,
            severity=severity,
            source_type=source_type,
            source_id=source_id,
            dedupe_key=dedupe_key,
            payload_json=payload,
            event_at=event_at,
            created_at=now,
        )
        session.add(event)
        return event

    _refresh_event(existing, severity, payload, event_at)
    return existing


def _refresh_event(
    event: InventoryAlertEvent,
    severity: AlertSeverity,
    payload: dict[str, Any],
    event_at: datetime,
) -> None:
    if event.status in {InventoryAlertEventStatus.CANCELLED, InventoryAlertEventStatus.NO_RECIPIENT}:
        event.status = InventoryAlertEventStatus.PENDING
        event.cancelled_at = None
    event.severity = severity
    event.payload_json = payload
    event.event_at = event_at
    event.last_error_type = None
    event.last_error_message = None
    event.last_error_at = None


def _cancel_event(event: InventoryAlertEvent, now: datetime) -> None:
    event.status = InventoryAlertEventStatus.CANCELLED
    event.cancelled_at = now


def _active_agencies(session: Session, agency_id: int | None) -> list[Agencies]:
    stmt = select(Agencies).where(Agencies.active.is_(True))
    if agency_id is not None:
        stmt = stmt.where(Agencies.id == agency_id)
    return list(session.execute(stmt).scalars().all())


def _load_state_audit_rows(
    session: Session,
    agency_id: int | None,
    item_location_keys: set[tuple[int, int, int]] | None = None,
) -> list[StateAuditRow]:
    stmt = (
        select(
            Agencies.id,
            Agencies.count_last_days,
            Agencies.alert_rare_scan_days,
            Items.id,
            Items.name,
            AgencyLocations.id,
            AgencyLocations.name,
            InventoryItemLocationState.total_quantity,
            InventoryItemLocationState.last_counted_at,
            InventoryItemLocationState.last_takeout_at,
        )
        .join(Items, Items.agency_id == Agencies.id)
        .join(AgencyLocations, AgencyLocations.agency_id == Agencies.id)
        .join(
            InventoryItemLocationState,
            (InventoryItemLocationState.agency_id == Agencies.id)
            & (InventoryItemLocationState.item_id == Items.id)
            & (InventoryItemLocationState.agency_location_id == AgencyLocations.id),
        )
        .where(Agencies.active.is_(True), Items.active.is_(True))
        .order_by(Agencies.id, Items.id, AgencyLocations.id)
    )
    if agency_id is not None:
        stmt = stmt.where(Agencies.id == agency_id)
    if item_location_keys:
        agency_ids = {scope_agency_id for scope_agency_id, _, _ in item_location_keys}
        item_ids = {item_id for _, item_id, _ in item_location_keys}
        location_ids = {location_id for _, _, location_id in item_location_keys}
        stmt = stmt.where(
            Agencies.id.in_(agency_ids),
            Items.id.in_(item_ids),
            AgencyLocations.id.in_(location_ids),
        )

    state_rows = [
        StateAuditRow(
            agency_id=row[0],
            count_last_days=int(row[1] or 0),
            alert_rare_scan_days=int(row[2] or 0),
            item_id=row[3],
            item_name=row[4],
            location_id=row[5],
            location_name=row[6],
            total_quantity=int(row[7] or 0),
            last_counted_at=row[8],
            last_takeout_at=row[9],
        )
        for row in session.execute(stmt).all()
    ]
    if not item_location_keys:
        return state_rows
    return [state_row for state_row in state_rows if (state_row.agency_id, state_row.item_id, state_row.location_id) in item_location_keys]


def _cancel_open_state_audit_events(
    session: Session,
    *,
    agency_id: int | None,
    item_location_keys: set[tuple[int, int, int]] | None,
    now: datetime,
) -> None:
    stmt = select(InventoryAlertEvent).where(
        InventoryAlertEvent.alert_type.in_(STATE_AUDIT_EVENT_TYPES),
        InventoryAlertEvent.status.in_(OPEN_EVENT_STATUSES),
    )
    if agency_id is not None:
        stmt = stmt.where(InventoryAlertEvent.agency_id == agency_id)
    if item_location_keys:
        stmt = stmt.where(InventoryAlertEvent.agency_id.in_({scope_agency_id for scope_agency_id, _, _ in item_location_keys}))

    for event in session.execute(stmt).scalars():
        if item_location_keys is not None and _alert_event_item_location_key(event) not in item_location_keys:
            continue
        _cancel_event(event, now)


def _alert_event_item_location_key(event: InventoryAlertEvent) -> tuple[int, int, int] | None:
    item_id = event.payload_json.get("item_id")
    location_id = event.payload_json.get("agency_location_id")
    if not isinstance(item_id, int) or not isinstance(location_id, int):
        return None
    return (event.agency_id, item_id, location_id)


def _state_audit_row_key(state_audit_row: StateAuditRow) -> tuple[int, int, int]:
    return (state_audit_row.agency_id, state_audit_row.item_id, state_audit_row.location_id)


def _load_action_item(session: Session, action_log: ActionLogs) -> Items | None:
    if action_log.item and action_log.item.agency_id == action_log.agency_id and action_log.item.active:
        return action_log.item
    if action_log.item_id is None:
        return None
    return get_agency_item(action_log.agency_id, action_log.item_id, session=session)


def _storage_history_name(
    session: Session,
    agency_id: int,
    storage_id: int | None,
) -> str | None:
    storage = _storage_row(session, agency_id, storage_id)
    return storage.history_name if storage and storage.agency_id == agency_id else None


def _storage_location_id(
    session: Session,
    agency_id: int,
    storage_id: int | None,
) -> int | None:
    storage = _storage_row(session, agency_id, storage_id)
    return storage.location_id if storage and storage.agency_id == agency_id else None


def _storage_row(
    session: Session,
    agency_id: int,
    storage_id: int | None,
) -> AgencyStorages | None:
    if storage_id is None:
        return None
    storage = session.get(AgencyStorages, storage_id)
    return storage if storage and storage.agency_id == agency_id else None


def _stale_count_key(item_id: int, agency_location_id: int, last_counted_at: datetime | None) -> str:
    stamp = _iso(last_counted_at) or "NEVER"
    return f"STALE_COUNT:item:{item_id}:location:{agency_location_id}:last_count:{stamp}"


def _rare_takeout_key(item_id: int, agency_location_id: int, last_takeout_at: datetime | None) -> str:
    stamp = _iso(last_takeout_at) or "NEVER"
    return f"RARE_TAKEOUT:item:{item_id}:location:{agency_location_id}:last_takeout:{stamp}"


def _days_since_current_date(now: datetime, observed_at: datetime | None) -> int | None:
    if observed_at is None:
        return None
    return (now.date() - observed_at.date()).days


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _now() -> datetime:
    return utc_now_naive()
