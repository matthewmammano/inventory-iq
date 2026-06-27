"""Discrete alert event generation and item/location state safety refresh."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import Agencies, AgencyLocations, AgencyStorages
from app.inventory.balance_service import get_location_last_takeout_at
from app.inventory.constants import OperationType
from app.inventory.item_queries import get_agency_item
from app.inventory.location_state_service import rebuild_item_location_states, recompute_item_location_state
from app.inventory.models import ActionLogs, InventoryItemLocationState, Items
from app.shared.clock import utc_now_naive

from .constants import ACTION_ALERT_TYPES, AlertSeverity, AlertSourceType, AlertType, InventoryAlertEventStatus
from .models import InventoryAlertEvent

OPEN_EVENT_STATUSES = (InventoryAlertEventStatus.PENDING, InventoryAlertEventStatus.QUEUED, InventoryAlertEventStatus.ERROR)


@dataclass(frozen=True)
class ScheduledAlertState:
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
    """Create discrete action events and refresh affected state-derived alert data."""
    if not action_logs:
        return

    now = _now()
    for action in action_logs:
        _record_scan_activity_event(session, action, now)
        _sync_action_rare_takeout_event(session, action, now)

    affected_item_locations = _affected_item_locations(session, action_logs)
    for agency_id, item_id, location_id in affected_item_locations:
        recompute_item_location_state(session, agency_id, item_id, location_id)

    logger.info(
        "Inventory action alert state refreshed",
        extra={"action_count": len(action_logs), "affected_item_location_count": len(affected_item_locations)},
    )


def generate_scheduled_alerts(session: Session, agency_id: int | None = None) -> int:
    """Run the inventory alert safety audit and discrete aging checks."""
    now = _now()
    state_count = rebuild_item_location_states(session, agency_id)
    agencies = _active_agencies(session, agency_id)
    if agency_id is not None and not agencies:
        logger.warning(
            "Scheduled alert audit could not find an active agency for the requested id",
            extra={"agency_id": agency_id},
        )

    scheduled_states = _scheduled_alert_states(session, agency_id)
    event_cache = _event_cache_for_scheduled_states(session, scheduled_states)
    for state in scheduled_states:
        _sync_stale_count_state(session, state, event_cache, now)
        _sync_rare_takeout_state(session, state, event_cache, now)
    session.flush()

    logger.info(
        "Inventory alert safety audit finished",
        extra={"agency_id": agency_id, "state_rows_checked": state_count, "event_checks": len(scheduled_states)},
    )
    return state_count + len(scheduled_states)


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
        severity=AlertSeverity.WARNING,
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
    action: ActionLogs,
    now: datetime,
) -> None:
    alert_type = ACTION_ALERT_TYPES.get(action.operation_type)
    if alert_type is None or action.item_id is None:
        return

    item = _action_item(session, action)
    if item is None:
        return

    payload = {
        "action_log_id": action.id,
        "item_id": item.id,
        "item_name": item.name,
        "operation_type": action.operation_type.value,
        "quantity": action.quantity_delta,
        "admin_action": bool(action.admin_action),
        "from_agency_location_id": _storage_location_id(session, action.agency_id, action.from_location_id),
        "to_agency_location_id": _storage_location_id(session, action.agency_id, action.to_location_id),
        "from_location_name": _storage_history_name(session, action.agency_id, action.from_location_id),
        "to_location_name": _storage_history_name(session, action.agency_id, action.to_location_id),
        "time_scanned": _iso(action.time_scanned),
    }
    _upsert_event(
        session,
        agency_id=action.agency_id,
        alert_type=alert_type,
        severity=AlertSeverity.INFO,
        source_type=AlertSourceType.ACTION_LOG,
        source_id=action.id,
        dedupe_key=f"ACTION_LOG:{action.id}",
        payload=payload,
        event_at=action.time_scanned or now,
        now=now,
    )


def _sync_action_rare_takeout_event(
    session: Session,
    action: ActionLogs,
    now: datetime,
) -> None:
    if action.operation_type != OperationType.TAKEOUT or action.item_id is None:
        return
    storage = _storage_row(session, action.agency_id, action.from_location_id)
    agency = session.get(Agencies, action.agency_id)
    item = _action_item(session, action)
    if storage is None or storage.location is None or agency is None or item is None:
        return
    state = recompute_item_location_state(session, agency.id, item.id, storage.location_id)
    _sync_rare_takeout_event(session, agency, item, storage.location, state, now)


def _sync_stale_count_event(
    session: Session,
    agency: Agencies,
    item: Items,
    location: AgencyLocations,
    state: InventoryItemLocationState | None,
    now: datetime,
) -> None:
    days = int(agency.count_last_days or 0)
    if days <= 0 or state is None:
        _cancel_open_events(session, agency.id, _stale_count_key(item.id, location.id, None), now)
        return

    days_since = _days_since_current_date(now, state.last_counted_at)
    if days_since is not None and days_since < days:
        _cancel_open_events(session, agency.id, _stale_count_key(item.id, location.id, state.last_counted_at), now)
        return

    event_at = state.last_counted_at or now
    _upsert_event(
        session,
        agency_id=agency.id,
        alert_type=AlertType.STALE_COUNT,
        severity=AlertSeverity.WARNING,
        source_type=AlertSourceType.STALE_COUNT_AUDIT,
        source_id=None,
        dedupe_key=_stale_count_key(item.id, location.id, state.last_counted_at),
        payload={
            "item_id": item.id,
            "item_name": item.name,
            "agency_location_id": location.id,
            "location_name": location.name,
            "days_since_last_count": days_since,
            "current_total": state.total_quantity,
            "last_counted_at": _iso(state.last_counted_at),
        },
        event_at=event_at,
        now=now,
    )


def _sync_rare_takeout_event(
    session: Session,
    agency: Agencies,
    item: Items,
    location: AgencyLocations,
    state: InventoryItemLocationState | None,
    now: datetime,
) -> None:
    days = int(agency.alert_rare_scan_days or 0)
    if days <= 0 or state is None:
        _cancel_open_events(session, agency.id, _rare_takeout_key(item.id, location.id, None), now)
        return

    last_takeout = state.last_takeout_at or get_location_last_takeout_at(session, agency.id, item.id, location.id)
    if last_takeout is None:
        _cancel_open_events(session, agency.id, _rare_takeout_key(item.id, location.id, None), now)
        return

    days_since = _days_since_current_date(now, last_takeout)
    if days_since is not None and days_since < days:
        _cancel_open_events(session, agency.id, _rare_takeout_key(item.id, location.id, last_takeout), now)
        return

    _upsert_event(
        session,
        agency_id=agency.id,
        alert_type=AlertType.RARE_TAKEOUT,
        severity=AlertSeverity.WARNING,
        source_type=AlertSourceType.RARE_TAKEOUT_AUDIT,
        source_id=None,
        dedupe_key=_rare_takeout_key(item.id, location.id, last_takeout),
        payload={
            "item_id": item.id,
            "item_name": item.name,
            "agency_location_id": location.id,
            "location_name": location.name,
            "days_since_last_takeout": days_since,
            "last_takeout_at": _iso(last_takeout),
            "current_total": state.total_quantity,
            "rare_scan_days": days,
        },
        event_at=last_takeout,
        now=now,
    )


def _sync_stale_count_state(
    session: Session,
    state: ScheduledAlertState,
    event_cache: dict[tuple[int, str], InventoryAlertEvent],
    now: datetime,
) -> None:
    days = int(state.count_last_days or 0)
    if days <= 0:
        _cancel_cached_event(event_cache, state.agency_id, _stale_count_key(state.item_id, state.location_id, None), now)
        return

    days_since = _days_since_current_date(now, state.last_counted_at)
    if days_since is not None and days_since < days:
        _cancel_cached_event(event_cache, state.agency_id, _stale_count_key(state.item_id, state.location_id, state.last_counted_at), now)
        return

    event_at = state.last_counted_at or now
    _upsert_cached_event(
        session,
        event_cache,
        agency_id=state.agency_id,
        alert_type=AlertType.STALE_COUNT,
        severity=AlertSeverity.WARNING,
        source_type=AlertSourceType.STALE_COUNT_AUDIT,
        source_id=None,
        dedupe_key=_stale_count_key(state.item_id, state.location_id, state.last_counted_at),
        payload={
            "item_id": state.item_id,
            "item_name": state.item_name,
            "agency_location_id": state.location_id,
            "location_name": state.location_name,
            "days_since_last_count": days_since,
            "current_total": state.total_quantity,
            "last_counted_at": _iso(state.last_counted_at),
        },
        event_at=event_at,
        now=now,
    )


def _sync_rare_takeout_state(
    session: Session,
    state: ScheduledAlertState,
    event_cache: dict[tuple[int, str], InventoryAlertEvent],
    now: datetime,
) -> None:
    days = int(state.alert_rare_scan_days or 0)
    if days <= 0 or state.last_takeout_at is None:
        _cancel_cached_event(event_cache, state.agency_id, _rare_takeout_key(state.item_id, state.location_id, None), now)
        return

    days_since = _days_since_current_date(now, state.last_takeout_at)
    if days_since is not None and days_since < days:
        _cancel_cached_event(event_cache, state.agency_id, _rare_takeout_key(state.item_id, state.location_id, state.last_takeout_at), now)
        return

    _upsert_cached_event(
        session,
        event_cache,
        agency_id=state.agency_id,
        alert_type=AlertType.RARE_TAKEOUT,
        severity=AlertSeverity.WARNING,
        source_type=AlertSourceType.RARE_TAKEOUT_AUDIT,
        source_id=None,
        dedupe_key=_rare_takeout_key(state.item_id, state.location_id, state.last_takeout_at),
        payload={
            "item_id": state.item_id,
            "item_name": state.item_name,
            "agency_location_id": state.location_id,
            "location_name": state.location_name,
            "days_since_last_takeout": days_since,
            "last_takeout_at": _iso(state.last_takeout_at),
            "current_total": state.total_quantity,
            "rare_scan_days": days,
        },
        event_at=state.last_takeout_at,
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


def _upsert_cached_event(
    session: Session,
    event_cache: dict[tuple[int, str], InventoryAlertEvent],
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
    existing = event_cache.get((agency_id, dedupe_key))
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
        event_cache[(agency_id, dedupe_key)] = event
        return event

    _refresh_event(existing, severity, payload, event_at)
    return existing


def _refresh_event(
    event: InventoryAlertEvent,
    severity: AlertSeverity,
    payload: dict[str, Any],
    event_at: datetime,
) -> None:
    if event.status == InventoryAlertEventStatus.CANCELLED:
        event.status = InventoryAlertEventStatus.PENDING
        event.cancelled_at = None
    event.severity = severity
    event.payload_json = payload
    event.event_at = event_at
    event.last_error_type = None
    event.last_error_message = None
    event.last_error_at = None


def _cancel_open_events(session: Session, agency_id: int, dedupe_key: str, now: datetime) -> None:
    event = session.scalar(
        select(InventoryAlertEvent).where(
            InventoryAlertEvent.agency_id == agency_id,
            InventoryAlertEvent.dedupe_key == dedupe_key,
            InventoryAlertEvent.status.in_(OPEN_EVENT_STATUSES),
        )
    )
    if event is not None:
        _cancel_event(event, now)


def _cancel_cached_event(
    event_cache: dict[tuple[int, str], InventoryAlertEvent],
    agency_id: int,
    dedupe_key: str,
    now: datetime,
) -> None:
    event = event_cache.get((agency_id, dedupe_key))
    if event is not None and event.status in OPEN_EVENT_STATUSES:
        _cancel_event(event, now)


def _cancel_event(event: InventoryAlertEvent, now: datetime) -> None:
    event.status = InventoryAlertEventStatus.CANCELLED
    event.cancelled_at = now


def _active_agencies(session: Session, agency_id: int | None) -> list[Agencies]:
    stmt = select(Agencies).where(Agencies.active.is_(True))
    if agency_id is not None:
        stmt = stmt.where(Agencies.id == agency_id)
    return list(session.execute(stmt).scalars().all())


def _scheduled_alert_states(session: Session, agency_id: int | None) -> list[ScheduledAlertState]:
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

    return [
        ScheduledAlertState(
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


def _event_cache_for_scheduled_states(
    session: Session,
    states: list[ScheduledAlertState],
) -> dict[tuple[int, str], InventoryAlertEvent]:
    keys = _scheduled_event_keys(states)
    if not keys:
        return {}
    agency_ids = {agency_id for agency_id, _dedupe_key in keys}
    dedupe_keys = {dedupe_key for _agency_id, dedupe_key in keys}
    rows = session.execute(
        select(InventoryAlertEvent).where(
            InventoryAlertEvent.agency_id.in_(agency_ids),
            InventoryAlertEvent.dedupe_key.in_(dedupe_keys),
        )
    ).scalars()
    return {(event.agency_id, event.dedupe_key): event for event in rows}


def _scheduled_event_keys(states: list[ScheduledAlertState]) -> set[tuple[int, str]]:
    keys: set[tuple[int, str]] = set()
    for state in states:
        stale_stamp = None if state.count_last_days <= 0 else state.last_counted_at
        rare_stamp = None if state.alert_rare_scan_days <= 0 or state.last_takeout_at is None else state.last_takeout_at
        keys.add((state.agency_id, _stale_count_key(state.item_id, state.location_id, stale_stamp)))
        keys.add((state.agency_id, _rare_takeout_key(state.item_id, state.location_id, rare_stamp)))
    return keys


def _affected_item_locations(
    session: Session,
    action_logs: list[ActionLogs],
) -> set[tuple[int, int, int]]:
    storage_ids = sorted(
        {
            storage_id
            for action in action_logs
            for storage_id in (action.from_location_id, action.to_location_id)
            if action.item_id is not None and storage_id is not None
        }
    )
    if not storage_ids:
        return set()
    storages = session.execute(select(AgencyStorages).where(AgencyStorages.id.in_(storage_ids))).scalars()
    location_by_storage_id = {storage.id: storage.location_id for storage in storages}
    pairs: set[tuple[int, int, int]] = set()
    for action in action_logs:
        if action.item_id is None:
            continue
        for storage_id in (action.from_location_id, action.to_location_id):
            if storage_id is not None and storage_id in location_by_storage_id:
                pairs.add((action.agency_id, action.item_id, location_by_storage_id[storage_id]))
    return pairs


def _action_item(session: Session, action: ActionLogs) -> Items | None:
    if action.item and action.item.agency_id == action.agency_id and action.item.active:
        return action.item
    if action.item_id is None:
        return None
    return get_agency_item(action.agency_id, action.item_id, session=session)


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
