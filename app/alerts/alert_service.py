"""Discrete alert event generation and item/location state safety refresh."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.models import Agency, Location, Storage
from app.inventory.item_queries import get_agency_item
from app.inventory.location_state_service import ItemLocationKey, affected_item_location_keys_for_actions, rebuild_item_location_states
from app.inventory.models import ActionLog, InventoryExpirationBalance, InventoryItemLocationState, InventoryStorageBalance, Item
from app.shared.clock import utc_now_naive

from .constants import ACTION_ALERT_TYPES, ALERT_DEFINITIONS, AlertSeverity, AlertSourceType, AlertType, InventoryAlertEventStatus
from .models import InventoryAlertEvent
from .payloads import (
    ExpirationCountNeededPayload,
    ExpirationStockPayload,
    RareTakeoutPayload,
    ScanActivityPayload,
    StaleCountPayload,
    UnknownUpcPayload,
)

OPEN_EVENT_STATUSES = (
    InventoryAlertEventStatus.PENDING,
    InventoryAlertEventStatus.NO_RECIPIENT,
    InventoryAlertEventStatus.QUEUED,
    InventoryAlertEventStatus.ERROR,
)
STATE_AUDIT_EVENT_TYPES = (AlertType.STALE_COUNT, AlertType.RARE_TAKEOUT)
EXPIRATION_AUDIT_EVENT_TYPES = (AlertType.EXPIRED_STOCK, AlertType.EXPIRING_SOON, AlertType.EXPIRATION_COUNT_NEEDED)


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


@dataclass(frozen=True)
class ExpirationAuditRow:
    """Flat expiration row used by the scheduled audit without ORM relationship traversal."""

    agency_id: int
    item_id: int
    item_name: str
    storage_id: int
    storage_name: str
    location_id: int
    location_name: str
    expires_on: date
    quantity: int
    notice_days: int


@dataclass(frozen=True)
class ExpirationCountAuditRow:
    """Flat quantity mismatch row for tracked expiration counts."""

    agency_id: int
    item_id: int
    item_name: str
    storage_id: int
    storage_name: str
    location_id: int
    location_name: str
    storage_quantity: int
    tracked_expiration_quantity: int


def record_action_log_alerts(
    session: Session,
    action_logs: list[ActionLog],
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
    expiration_count = sync_expiration_audit_events(session, agency_id=agency_id)

    logger.info(
        "Inventory alert safety audit finished",
        extra={"agency_id": agency_id, "state_rows_checked": state_count, "event_checks": event_count, "expiration_checks": expiration_count},
    )
    return state_count + event_count + expiration_count


def sync_state_audit_events(
    session: Session,
    *,
    agency_id: int | None = None,
    item_location_keys: set[ItemLocationKey] | None = None,
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
    existing_events_by_key = _existing_state_audit_events_by_key(session, agency_id, item_location_keys)
    for state_audit_row in state_audit_rows:
        _sync_stale_count_state(session, state_audit_row, now, existing_events_by_key)
        _sync_rare_takeout_state(session, state_audit_row, now, existing_events_by_key)
    session.flush()
    return len(state_audit_rows)


def sync_expiration_audit_events(
    session: Session,
    *,
    agency_id: int | None = None,
    now: datetime | None = None,
) -> int:
    """Refresh expiration alert events from current tracked expiration balances."""
    now = now or _now()
    today = now.date()
    _cancel_open_expiration_audit_events(session, agency_id=agency_id, now=now)
    existing_events_by_key = _existing_expiration_audit_events_by_key(session, agency_id)
    rows_checked = 0

    for expiration_row in _load_expiration_audit_rows(session, agency_id):
        rows_checked += 1
        _sync_expiration_stock_state(session, expiration_row, today, now, existing_events_by_key)

    for count_row in _load_expiration_count_audit_rows(session, agency_id):
        rows_checked += 1
        _sync_expiration_count_needed_state(session, count_row, now, existing_events_by_key)

    session.flush()
    return rows_checked


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
        payload=UnknownUpcPayload(unknown_upc_id=unknown_upc_id, upc=upc, lookup_title=lookup_title, created_at=created_at).as_json(),
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
    action_log: ActionLog,
    now: datetime,
) -> None:
    alert_type = ACTION_ALERT_TYPES.get(action_log.operation_type)
    if alert_type is None or action_log.item_id is None:
        return

    item = _load_action_item(session, action_log)
    if item is None:
        return

    _upsert_event(
        session,
        agency_id=action_log.agency_id,
        alert_type=alert_type,
        severity=AlertSeverity.INFO,
        source_type=AlertSourceType.ACTION_LOG,
        source_id=action_log.id,
        dedupe_key=f"ACTION_LOG:{action_log.id}",
        payload=ScanActivityPayload(
            action_log_id=action_log.id,
            item_id=item.id,
            item_name=item.name,
            operation_type=action_log.operation_type.value,
            quantity=action_log.quantity,
            admin_action=bool(action_log.admin_action),
            from_agency_location_id=_storage_location_id(session, action_log.agency_id, action_log.from_storage_id),
            to_agency_location_id=_storage_location_id(session, action_log.agency_id, action_log.to_storage_id),
            from_location_name=_storage_history_name(session, action_log.agency_id, action_log.from_storage_id),
            to_location_name=_storage_history_name(session, action_log.agency_id, action_log.to_storage_id),
            time_scanned=action_log.time_scanned,
        ).as_json(),
        event_at=action_log.time_scanned or now,
        now=now,
    )


def _sync_stale_count_state(
    session: Session,
    state_audit_row: StateAuditRow,
    now: datetime,
    existing_events_by_key: dict[tuple[int, str], InventoryAlertEvent],
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
        payload=StaleCountPayload(
            item_id=state_audit_row.item_id,
            item_name=state_audit_row.item_name,
            agency_location_id=state_audit_row.location_id,
            location_name=state_audit_row.location_name,
            days_since_last_count=days_since,
            current_total=state_audit_row.total_quantity,
            last_counted_at=state_audit_row.last_counted_at,
        ).as_json(),
        event_at=event_at,
        now=now,
        existing_events_by_key=existing_events_by_key,
    )


def _sync_rare_takeout_state(
    session: Session,
    state_audit_row: StateAuditRow,
    now: datetime,
    existing_events_by_key: dict[tuple[int, str], InventoryAlertEvent],
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
        payload=RareTakeoutPayload(
            item_id=state_audit_row.item_id,
            item_name=state_audit_row.item_name,
            agency_location_id=state_audit_row.location_id,
            location_name=state_audit_row.location_name,
            days_since_last_takeout=days_since,
            last_takeout_at=state_audit_row.last_takeout_at,
            current_total=state_audit_row.total_quantity,
            rare_scan_days=days,
        ).as_json(),
        event_at=state_audit_row.last_takeout_at,
        now=now,
        existing_events_by_key=existing_events_by_key,
    )


def _sync_expiration_stock_state(
    session: Session,
    expiration_row: ExpirationAuditRow,
    today: date,
    now: datetime,
    existing_events_by_key: dict[tuple[int, str], InventoryAlertEvent],
) -> None:
    days_until = (expiration_row.expires_on - today).days
    if days_until < 0:
        alert_type = AlertType.EXPIRED_STOCK
    elif days_until <= expiration_row.notice_days:
        alert_type = AlertType.EXPIRING_SOON
    else:
        return

    _upsert_event(
        session,
        agency_id=expiration_row.agency_id,
        alert_type=alert_type,
        severity=ALERT_DEFINITIONS[alert_type].severity,
        source_type=AlertSourceType.EXPIRATION_AUDIT,
        source_id=None,
        dedupe_key=_expiration_stock_key(alert_type, expiration_row.item_id, expiration_row.storage_id, expiration_row.expires_on),
        payload=ExpirationStockPayload(
            item_id=expiration_row.item_id,
            item_name=expiration_row.item_name,
            storage_id=expiration_row.storage_id,
            storage_name=expiration_row.storage_name,
            agency_location_id=expiration_row.location_id,
            location_name=expiration_row.location_name,
            expires_on=expiration_row.expires_on,
            quantity=expiration_row.quantity,
            days_until_expiration=days_until,
            notice_days=expiration_row.notice_days,
        ).as_json(),
        event_at=datetime.combine(expiration_row.expires_on, datetime.min.time()),
        now=now,
        existing_events_by_key=existing_events_by_key,
    )


def _sync_expiration_count_needed_state(
    session: Session,
    count_row: ExpirationCountAuditRow,
    now: datetime,
    existing_events_by_key: dict[tuple[int, str], InventoryAlertEvent],
) -> None:
    difference = count_row.storage_quantity - count_row.tracked_expiration_quantity
    if difference == 0:
        return

    _upsert_event(
        session,
        agency_id=count_row.agency_id,
        alert_type=AlertType.EXPIRATION_COUNT_NEEDED,
        severity=ALERT_DEFINITIONS[AlertType.EXPIRATION_COUNT_NEEDED].severity,
        source_type=AlertSourceType.EXPIRATION_AUDIT,
        source_id=None,
        dedupe_key=_expiration_count_needed_key(count_row.item_id, count_row.storage_id),
        payload=ExpirationCountNeededPayload(
            item_id=count_row.item_id,
            item_name=count_row.item_name,
            storage_id=count_row.storage_id,
            storage_name=count_row.storage_name,
            agency_location_id=count_row.location_id,
            location_name=count_row.location_name,
            storage_quantity=count_row.storage_quantity,
            tracked_expiration_quantity=count_row.tracked_expiration_quantity,
            difference=difference,
        ).as_json(),
        event_at=now,
        now=now,
        existing_events_by_key=existing_events_by_key,
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
    existing_events_by_key: dict[tuple[int, str], InventoryAlertEvent] | None = None,
) -> InventoryAlertEvent:
    cache_key = (agency_id, dedupe_key)
    existing = existing_events_by_key.get(cache_key) if existing_events_by_key is not None else None
    if existing is None and existing_events_by_key is None:
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
        if existing_events_by_key is not None:
            existing_events_by_key[cache_key] = event
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


def _active_agencies(session: Session, agency_id: int | None) -> list[Agency]:
    stmt = select(Agency).where(Agency.active.is_(True))
    if agency_id is not None:
        stmt = stmt.where(Agency.id == agency_id)
    return list(session.execute(stmt).scalars().all())


def _load_state_audit_rows(
    session: Session,
    agency_id: int | None,
    item_location_keys: set[ItemLocationKey] | None = None,
) -> list[StateAuditRow]:
    stmt = (
        select(
            Agency.id,
            Agency.count_last_days,
            Agency.alert_rare_scan_days,
            Item.id,
            Item.name,
            Location.id,
            Location.name,
            InventoryItemLocationState.total_quantity,
            InventoryItemLocationState.last_counted_at,
            InventoryItemLocationState.last_takeout_at,
        )
        .join(Item, Item.agency_id == Agency.id)
        .join(Location, Location.agency_id == Agency.id)
        .join(
            InventoryItemLocationState,
            (InventoryItemLocationState.agency_id == Agency.id)
            & (InventoryItemLocationState.item_id == Item.id)
            & (InventoryItemLocationState.agency_location_id == Location.id),
        )
        .where(Agency.active.is_(True), Item.active.is_(True))
        .order_by(Agency.id, Item.id, Location.id)
    )
    if agency_id is not None:
        stmt = stmt.where(Agency.id == agency_id)
    if item_location_keys:
        agency_ids = {key.agency_id for key in item_location_keys}
        item_ids = {key.item_id for key in item_location_keys}
        location_ids = {key.agency_location_id for key in item_location_keys}
        stmt = stmt.where(
            Agency.id.in_(agency_ids),
            Item.id.in_(item_ids),
            Location.id.in_(location_ids),
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
    return [state_row for state_row in state_rows if _state_audit_row_key(state_row) in item_location_keys]


def _load_expiration_audit_rows(session: Session, agency_id: int | None) -> list[ExpirationAuditRow]:
    stmt = (
        select(
            Agency.id,
            Item.id,
            Item.name,
            Storage.id,
            Storage.name,
            Location.id,
            Location.name,
            InventoryExpirationBalance.expires_on,
            InventoryExpirationBalance.quantity,
            func.coalesce(Item.expiration_notice_days_override, Agency.expiration_notice_days),
        )
        .join(Item, Item.agency_id == Agency.id)
        .join(
            InventoryExpirationBalance,
            (InventoryExpirationBalance.agency_id == Agency.id) & (InventoryExpirationBalance.item_id == Item.id),
        )
        .join(Storage, Storage.id == InventoryExpirationBalance.storage_id)
        .join(Location, Location.id == Storage.location_id)
        .where(
            Agency.active.is_(True),
            Item.active.is_(True),
            Item.expiration_tracking_enabled.is_(True),
            InventoryExpirationBalance.quantity > 0,
        )
        .order_by(Agency.id, InventoryExpirationBalance.expires_on, Item.name, Location.name, Storage.name)
    )
    if agency_id is not None:
        stmt = stmt.where(Agency.id == agency_id)
    return [
        ExpirationAuditRow(
            agency_id=row[0],
            item_id=row[1],
            item_name=row[2],
            storage_id=row[3],
            storage_name=row[4],
            location_id=row[5],
            location_name=row[6],
            expires_on=row[7],
            quantity=int(row[8] or 0),
            notice_days=int(row[9] or 0),
        )
        for row in session.execute(stmt).all()
    ]


def _load_expiration_count_audit_rows(session: Session, agency_id: int | None) -> list[ExpirationCountAuditRow]:
    storage_rows = _expiration_storage_totals(session, agency_id)
    expiration_totals = _expiration_tracked_totals(session, agency_id)
    keys = sorted(storage_rows.keys() | expiration_totals.keys())
    rows: list[ExpirationCountAuditRow] = []
    for key in keys:
        base_row = storage_rows.get(key) or expiration_totals[key]
        storage_quantity = storage_rows[key].storage_quantity if key in storage_rows else 0
        tracked_quantity = expiration_totals[key].tracked_expiration_quantity if key in expiration_totals else 0
        if storage_quantity != tracked_quantity:
            rows.append(
                ExpirationCountAuditRow(
                    agency_id=base_row.agency_id,
                    item_id=base_row.item_id,
                    item_name=base_row.item_name,
                    storage_id=base_row.storage_id,
                    storage_name=base_row.storage_name,
                    location_id=base_row.location_id,
                    location_name=base_row.location_name,
                    storage_quantity=storage_quantity,
                    tracked_expiration_quantity=tracked_quantity,
                )
            )
    return rows


def _expiration_storage_totals(session: Session, agency_id: int | None) -> dict[tuple[int, int, int], ExpirationCountAuditRow]:
    stmt = (
        select(
            Agency.id,
            Item.id,
            Item.name,
            Storage.id,
            Storage.name,
            Location.id,
            Location.name,
            InventoryStorageBalance.quantity,
        )
        .join(Item, Item.agency_id == Agency.id)
        .join(
            InventoryStorageBalance,
            (InventoryStorageBalance.agency_id == Agency.id) & (InventoryStorageBalance.item_id == Item.id),
        )
        .join(Storage, Storage.id == InventoryStorageBalance.storage_id)
        .join(Location, Location.id == Storage.location_id)
        .where(Agency.active.is_(True), Item.active.is_(True), Item.expiration_tracking_enabled.is_(True))
    )
    if agency_id is not None:
        stmt = stmt.where(Agency.id == agency_id)
    return {
        (row[0], row[1], row[3]): ExpirationCountAuditRow(
            agency_id=row[0],
            item_id=row[1],
            item_name=row[2],
            storage_id=row[3],
            storage_name=row[4],
            location_id=row[5],
            location_name=row[6],
            storage_quantity=int(row[7] or 0),
            tracked_expiration_quantity=0,
        )
        for row in session.execute(stmt).all()
    }


def _expiration_tracked_totals(session: Session, agency_id: int | None) -> dict[tuple[int, int, int], ExpirationCountAuditRow]:
    stmt = (
        select(
            Agency.id,
            Item.id,
            Item.name,
            Storage.id,
            Storage.name,
            Location.id,
            Location.name,
            func.coalesce(func.sum(InventoryExpirationBalance.quantity), 0),
        )
        .join(Item, Item.agency_id == Agency.id)
        .join(
            InventoryExpirationBalance,
            (InventoryExpirationBalance.agency_id == Agency.id) & (InventoryExpirationBalance.item_id == Item.id),
        )
        .join(Storage, Storage.id == InventoryExpirationBalance.storage_id)
        .join(Location, Location.id == Storage.location_id)
        .where(Agency.active.is_(True), Item.active.is_(True), Item.expiration_tracking_enabled.is_(True))
        .group_by(Agency.id, Item.id, Item.name, Storage.id, Storage.name, Location.id, Location.name)
    )
    if agency_id is not None:
        stmt = stmt.where(Agency.id == agency_id)
    return {
        (row[0], row[1], row[3]): ExpirationCountAuditRow(
            agency_id=row[0],
            item_id=row[1],
            item_name=row[2],
            storage_id=row[3],
            storage_name=row[4],
            location_id=row[5],
            location_name=row[6],
            storage_quantity=0,
            tracked_expiration_quantity=int(row[7] or 0),
        )
        for row in session.execute(stmt).all()
    }


def _existing_state_audit_events_by_key(
    session: Session,
    agency_id: int | None,
    item_location_keys: set[ItemLocationKey] | None,
) -> dict[tuple[int, str], InventoryAlertEvent]:
    stmt = select(InventoryAlertEvent).where(InventoryAlertEvent.alert_type.in_(STATE_AUDIT_EVENT_TYPES))
    if agency_id is not None:
        stmt = stmt.where(InventoryAlertEvent.agency_id == agency_id)
    if item_location_keys:
        stmt = stmt.where(InventoryAlertEvent.agency_id.in_({key.agency_id for key in item_location_keys}))
    events = session.execute(stmt).scalars()
    if item_location_keys is None:
        return {(event.agency_id, event.dedupe_key): event for event in events}
    return {(event.agency_id, event.dedupe_key): event for event in events if _alert_event_item_location_key(event) in item_location_keys}


def _existing_expiration_audit_events_by_key(
    session: Session,
    agency_id: int | None,
) -> dict[tuple[int, str], InventoryAlertEvent]:
    stmt = select(InventoryAlertEvent).where(InventoryAlertEvent.alert_type.in_(EXPIRATION_AUDIT_EVENT_TYPES))
    if agency_id is not None:
        stmt = stmt.where(InventoryAlertEvent.agency_id == agency_id)
    return {(event.agency_id, event.dedupe_key): event for event in session.execute(stmt).scalars()}


def _cancel_open_state_audit_events(
    session: Session,
    *,
    agency_id: int | None,
    item_location_keys: set[ItemLocationKey] | None,
    now: datetime,
) -> None:
    stmt = select(InventoryAlertEvent).where(
        InventoryAlertEvent.alert_type.in_(STATE_AUDIT_EVENT_TYPES),
        InventoryAlertEvent.status.in_(OPEN_EVENT_STATUSES),
    )
    if agency_id is not None:
        stmt = stmt.where(InventoryAlertEvent.agency_id == agency_id)
    if item_location_keys:
        stmt = stmt.where(InventoryAlertEvent.agency_id.in_({key.agency_id for key in item_location_keys}))

    for event in session.execute(stmt).scalars():
        if item_location_keys is not None and _alert_event_item_location_key(event) not in item_location_keys:
            continue
        _cancel_event(event, now)


def _cancel_open_expiration_audit_events(session: Session, *, agency_id: int | None, now: datetime) -> None:
    stmt = select(InventoryAlertEvent).where(
        InventoryAlertEvent.alert_type.in_(EXPIRATION_AUDIT_EVENT_TYPES),
        InventoryAlertEvent.status.in_(OPEN_EVENT_STATUSES),
    )
    if agency_id is not None:
        stmt = stmt.where(InventoryAlertEvent.agency_id == agency_id)
    for event in session.execute(stmt).scalars():
        _cancel_event(event, now)


def _alert_event_item_location_key(event: InventoryAlertEvent) -> ItemLocationKey | None:
    item_id = event.payload_json.get("item_id")
    location_id = event.payload_json.get("agency_location_id")
    if not isinstance(item_id, int) or not isinstance(location_id, int):
        return None
    return ItemLocationKey(event.agency_id, item_id, location_id)


def _state_audit_row_key(state_audit_row: StateAuditRow) -> ItemLocationKey:
    return ItemLocationKey(state_audit_row.agency_id, state_audit_row.item_id, state_audit_row.location_id)


def _load_action_item(session: Session, action_log: ActionLog) -> Item | None:
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
) -> Storage | None:
    if storage_id is None:
        return None
    storage = session.get(Storage, storage_id)
    return storage if storage and storage.agency_id == agency_id else None


def _stale_count_key(item_id: int, agency_location_id: int, last_counted_at: datetime | None) -> str:
    stamp = _iso(last_counted_at) or "NEVER"
    return f"STALE_COUNT:item:{item_id}:location:{agency_location_id}:last_count:{stamp}"


def _rare_takeout_key(item_id: int, agency_location_id: int, last_takeout_at: datetime | None) -> str:
    stamp = _iso(last_takeout_at) or "NEVER"
    return f"RARE_TAKEOUT:item:{item_id}:location:{agency_location_id}:last_takeout:{stamp}"


def _expiration_stock_key(alert_type: AlertType, item_id: int, storage_id: int, expires_on: date) -> str:
    return f"{alert_type.value}:item:{item_id}:storage:{storage_id}:expires:{expires_on.isoformat()}"


def _expiration_count_needed_key(item_id: int, storage_id: int) -> str:
    return f"EXPIRATION_COUNT_NEEDED:item:{item_id}:storage:{storage_id}"


def _days_since_current_date(now: datetime, observed_at: datetime | None) -> int | None:
    if observed_at is None:
        return None
    return (now.date() - observed_at.date()).days


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _now() -> datetime:
    return utc_now_naive()
