"""Alert generation and state sync."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import Agencies, AgencyLocations, AgencyStorages
from app.inventory.constants import OperationType
from app.inventory.item_queries import list_items
from app.inventory.models import ActionLogs, Items
from app.prediction.estimator import (
    days_to_threshold,
    effective_lead_time_days,
    get_location_item_quantity,
    project_location_item,
)
from app.prediction.segments import get_location_storage_ids
from app.shared.clock import utc_now_naive

from .constants import AlertAction, AlertCadence, AlertType
from .models import AlertRecords

STOCK_PRIORITY = (
    AlertType.STOCKOUT,
    AlertType.STOCKOUT_PRED,
    AlertType.LOW,
    AlertType.LOW_PRED,
)

ACTION_ALERT_TYPES = {
    OperationType.COUNT: AlertType.COUNT_ACTION,
    OperationType.RESTOCK: AlertType.RESTOCK_ACTION,
    OperationType.TAKEOUT: AlertType.TAKEOUT_ACTION,
    OperationType.TRANSFER: AlertType.TRANSFER_ACTION,
}

OPEN_ALERT_ACTIONS = (AlertAction.PENDING, AlertAction.SUPPRESSED)
type QuantitySnapshot = dict[tuple[int, int, int], tuple[int, int]]


def record_action_log_alerts(
    session: Session,
    action_logs: list[ActionLogs],
    quantity_snapshots: QuantitySnapshot | None = None,
) -> None:
    """Create scan activity alerts and refresh actual stock alerts."""
    if not action_logs:
        return

    now = _now()
    for action in action_logs:
        _record_scan_activity(session, action, now)

    for agency_id, item_id, location_id in _affected_item_locations(session, action_logs):
        agency = session.get(Agencies, agency_id)
        item = session.get(Items, item_id)
        if agency and item:
            snapshot = (
                None
                if quantity_snapshots is None
                else quantity_snapshots.get((agency_id, item_id, location_id))
            )
            if snapshot is not None:
                _sync_mutation_stock_alerts(session, agency, item, location_id, now, snapshot)


def generate_scheduled_alerts(session: Session, agency_id: int | None = None) -> int:
    """Generate daily audit alerts for active agencies."""
    now = _now()
    stmt = select(Agencies).where(Agencies.active.is_(True))
    if agency_id is not None:
        stmt = stmt.where(Agencies.id == agency_id)

    count = 0
    for agency in session.execute(stmt).scalars().all():
        for location in agency.locations:
            for item in list_items(agency.id, session=session):
                _sync_stock_alerts(
                    session, agency, item, location.id, now, include_predictions=True
                )
                _sync_stale_count_alert(session, agency, item, location, now)
                _sync_rare_takeout_alert(session, agency, item, location, now)
                count += 1

    logger.info("Scheduled alert audit complete", extra={"agency_id": agency_id, "rows": count})
    return count


def _record_scan_activity(session: Session, action: ActionLogs, now: datetime) -> None:
    alert_type = ACTION_ALERT_TYPES.get(action.operation_type)
    if alert_type is None or action.item_id is None:
        return

    item = action.item or session.get(Items, action.item_id)
    details = {
        "action_log_id": action.id,
        "item_id": action.item_id,
        "item_name": item.name if item else "Unknown item",
        "operation_type": action.operation_type.value,
        "quantity": action.quantity_delta,
        "admin_action": bool(action.admin_action),
        "from_location_name": _storage_history_name(session, action.from_location_id),
        "to_location_name": _storage_history_name(session, action.to_location_id),
        "time_scanned": _iso(action.time_scanned),
    }
    _upsert_alert(session, action.agency_id, alert_type, details, now)


def _sync_stock_alerts(
    session: Session,
    agency: Agencies,
    item: Items,
    agency_location_id: int,
    now: datetime,
    *,
    include_predictions: bool,
) -> None:
    if not include_predictions:
        return

    location = session.get(AgencyLocations, agency_location_id)
    if location is None:
        return

    details_by_type = _stock_details_by_type(session, agency, item, location, include_predictions)
    active_types = set(details_by_type)
    top_type = next(
        (alert_type for alert_type in STOCK_PRIORITY if alert_type in active_types), None
    )

    for alert_type in STOCK_PRIORITY:
        identity = _stock_identity(item.id, agency_location_id)
        if alert_type not in active_types:
            _set_matching_action(session, agency.id, alert_type, identity, AlertAction.CLEARED, now)
            continue

        action = AlertAction.PENDING if alert_type == top_type else AlertAction.SUPPRESSED
        _upsert_alert(
            session,
            agency.id,
            alert_type,
            details_by_type[alert_type],
            now,
            desired_action=action,
        )


def _sync_mutation_stock_alerts(
    session: Session,
    agency: Agencies,
    item: Items,
    agency_location_id: int,
    now: datetime,
    snapshot: tuple[int, int],
) -> None:
    location = session.get(AgencyLocations, agency_location_id)
    if location is None:
        return

    before_total, after_total = snapshot
    details_by_type = _stock_details_by_type(
        session, agency, item, location, include_predictions=False
    )
    crossed_types = _crossed_stock_types(before_total, after_total, int(item.min_quantity or 0))
    top_type = next(
        (alert_type for alert_type in STOCK_PRIORITY if alert_type in crossed_types), None
    )

    for alert_type in STOCK_PRIORITY:
        identity = _stock_identity(item.id, agency_location_id)
        if alert_type not in details_by_type:
            _set_matching_action(session, agency.id, alert_type, identity, AlertAction.CLEARED, now)
            continue
        if alert_type in crossed_types:
            action = AlertAction.PENDING if alert_type == top_type else AlertAction.SUPPRESSED
            _upsert_alert(
                session,
                agency.id,
                alert_type,
                details_by_type[alert_type],
                now,
                desired_action=action,
            )
            continue
        if top_type and _is_lower_priority(alert_type, top_type):
            _set_matching_action(
                session, agency.id, alert_type, identity, AlertAction.SUPPRESSED, now
            )
        _refresh_open_alert(session, agency.id, alert_type, identity, details_by_type[alert_type])


def _stock_details_by_type(
    session: Session,
    agency: Agencies,
    item: Items,
    location: AgencyLocations,
    include_predictions: bool,
) -> dict[AlertType, dict[str, Any]]:
    min_quantity = int(item.min_quantity or 0)
    lead_time_days = effective_lead_time_days(agency.lead_time_days, item.restock_delivery_days)
    projection = project_location_item(session, agency.id, item, location.id)
    current_total = projection.current_quantity
    base = {
        "item_id": item.id,
        "item_name": item.name,
        "agency_location_id": location.id,
        "location_name": location.name,
        "current_total": current_total,
        "min_quantity": min_quantity,
        "lead_time_days": lead_time_days,
    }

    alerts: dict[AlertType, dict[str, Any]] = {}
    if current_total <= 0:
        alerts[AlertType.STOCKOUT] = dict(base)
    if current_total < min_quantity:
        alerts[AlertType.LOW] = dict(base)

    if include_predictions and lead_time_days > 0:
        _add_prediction_alerts(alerts, base, projection, min_quantity, lead_time_days)
    return alerts


def _add_prediction_alerts(
    alerts: dict[AlertType, dict[str, Any]],
    base: dict[str, Any],
    projection,
    min_quantity: int,
    lead_time_days: int,
) -> None:
    days_stockout = days_to_threshold(projection.current_quantity, projection.trend_per_day, 0)
    days_low = days_to_threshold(
        projection.current_quantity, projection.trend_per_day, min_quantity
    )
    if days_stockout is not None and 0 < days_stockout <= lead_time_days:
        alerts[AlertType.STOCKOUT_PRED] = {
            **base,
            "days_until_stockout": round(days_stockout, 1),
            "confidence_percent": projection.confidence_percent,
        }
    if days_low is not None and 0 < days_low <= lead_time_days:
        alerts[AlertType.LOW_PRED] = {
            **base,
            "days_until_low": round(days_low, 1),
            "confidence_percent": projection.confidence_percent,
        }


def _crossed_stock_types(before_total: int, after_total: int, min_quantity: int) -> set[AlertType]:
    crossed: set[AlertType] = set()
    if before_total > 0 and after_total <= 0:
        crossed.add(AlertType.STOCKOUT)
    if before_total >= min_quantity > after_total:
        crossed.add(AlertType.LOW)
    return crossed


def _is_lower_priority(alert_type: AlertType, top_type: AlertType) -> bool:
    return STOCK_PRIORITY.index(alert_type) > STOCK_PRIORITY.index(top_type)


def _sync_stale_count_alert(
    session: Session,
    agency: Agencies,
    item: Items,
    location: AgencyLocations,
    now: datetime,
) -> None:
    days = int(agency.count_last_days or 0)
    identity = _stock_identity(item.id, location.id)
    if days <= 0:
        _set_matching_action(
            session, agency.id, AlertType.STALE_COUNT, identity, AlertAction.CLEARED, now
        )
        return

    last_counted = _last_location_action_at(
        session, agency.id, item.id, location.id, OperationType.COUNT
    )
    days_since = None if last_counted is None else (now.date() - last_counted.date()).days
    if days_since is not None and days_since < days:
        _set_matching_action(
            session, agency.id, AlertType.STALE_COUNT, identity, AlertAction.CLEARED, now
        )
        return

    details = {
        **identity,
        "item_name": item.name,
        "location_name": location.name,
        "days_since_last_count": days_since,
        "current_total": get_location_item_quantity(session, agency.id, item.id, location.id),
        "last_counted_at": _iso(last_counted),
    }
    _upsert_alert(session, agency.id, AlertType.STALE_COUNT, details, now)


def _sync_rare_takeout_alert(
    session: Session,
    agency: Agencies,
    item: Items,
    location: AgencyLocations,
    now: datetime,
) -> None:
    days = int(agency.alert_rare_scan_days or 0)
    identity = _stock_identity(item.id, location.id)
    if days <= 0:
        _set_matching_action(
            session, agency.id, AlertType.RARE_TAKEOUT, identity, AlertAction.CLEARED, now
        )
        return

    last_takeout = _last_location_action_at(
        session, agency.id, item.id, location.id, OperationType.TAKEOUT
    )
    if last_takeout is None:
        _set_matching_action(
            session, agency.id, AlertType.RARE_TAKEOUT, identity, AlertAction.CLEARED, now
        )
        return

    days_since = (now.date() - last_takeout.date()).days
    if days_since < days:
        _set_matching_action(
            session, agency.id, AlertType.RARE_TAKEOUT, identity, AlertAction.CLEARED, now
        )
        return

    details = {
        **identity,
        "item_name": item.name,
        "location_name": location.name,
        "days_since_last_takeout": days_since,
        "current_total": get_location_item_quantity(session, agency.id, item.id, location.id),
        "last_takeout_at": _iso(last_takeout),
        "rare_scan_days": days,
    }
    _upsert_alert(session, agency.id, AlertType.RARE_TAKEOUT, details, now)


def _upsert_alert(
    session: Session,
    agency_id: int,
    alert_type: AlertType,
    details: dict[str, Any],
    now: datetime,
    *,
    desired_action: AlertAction = AlertAction.PENDING,
) -> AlertRecords:
    existing = _find_open_alert(session, agency_id, alert_type, _identity(alert_type, details))
    scheduled = _scheduled_at(alert_type, now, _agency_timezone(session, agency_id))
    if existing is None:
        alert = AlertRecords(
            agency_id=agency_id,
            type=alert_type,
            action=desired_action,
            scheduled=scheduled,
            details_json=details,
            created_at=now,
            action_at=now,
        )
        session.add(alert)
        return alert

    existing.details_json = details
    if desired_action == AlertAction.PENDING:
        existing.scheduled = scheduled
    if existing.action != desired_action:
        existing.action = desired_action
        existing.action_at = now
    return existing


def _set_matching_action(
    session: Session,
    agency_id: int,
    alert_type: AlertType,
    identity: dict[str, Any],
    action: AlertAction,
    now: datetime,
) -> None:
    alert = _find_open_alert(session, agency_id, alert_type, identity)
    if alert and alert.action != action:
        alert.action = action
        alert.action_at = now


def _refresh_open_alert(
    session: Session,
    agency_id: int,
    alert_type: AlertType,
    identity: dict[str, Any],
    details: dict[str, Any],
) -> None:
    alert = _find_open_alert(session, agency_id, alert_type, identity)
    if alert:
        alert.details_json = details


def _find_open_alert(
    session: Session,
    agency_id: int,
    alert_type: AlertType,
    identity: dict[str, Any],
) -> AlertRecords | None:
    alerts = session.execute(
        select(AlertRecords).where(
            AlertRecords.agency_id == agency_id,
            AlertRecords.type == alert_type,
            AlertRecords.action.in_(OPEN_ALERT_ACTIONS),
        )
    ).scalars()
    return next(
        (alert for alert in alerts if _identity(alert_type, alert.details_json) == identity),
        None,
    )


def _identity(alert_type: AlertType, details: dict[str, Any]) -> dict[str, Any]:
    if alert_type in ACTION_ALERT_TYPES.values():
        return {"action_log_id": details.get("action_log_id")}
    return _stock_identity(details.get("item_id"), details.get("agency_location_id"))


def _stock_identity(item_id: int | None, agency_location_id: int | None) -> dict[str, Any]:
    return {"item_id": item_id, "agency_location_id": agency_location_id}


def _affected_item_locations(
    session: Session, action_logs: list[ActionLogs]
) -> set[tuple[int, int, int]]:
    pairs: set[tuple[int, int, int]] = set()
    for action in action_logs:
        if action.item_id is None:
            continue
        for storage_id in (action.from_location_id, action.to_location_id):
            storage = session.get(AgencyStorages, storage_id) if storage_id else None
            if storage:
                pairs.add((action.agency_id, action.item_id, storage.location_id))
    return pairs


def _last_location_action_at(
    session: Session,
    agency_id: int,
    item_id: int,
    agency_location_id: int,
    operation_type: OperationType,
) -> datetime | None:
    storage_ids = get_location_storage_ids(session, agency_id, agency_location_id)
    if not storage_ids:
        return None
    column = (
        ActionLogs.from_location_id
        if operation_type == OperationType.TAKEOUT
        else ActionLogs.to_location_id
    )
    row = session.execute(
        select(ActionLogs.time_scanned)
        .where(
            ActionLogs.agency_id == agency_id,
            ActionLogs.item_id == item_id,
            ActionLogs.operation_type == operation_type,
            column.in_(storage_ids),
        )
        .order_by(ActionLogs.time_scanned.desc())
        .limit(1)
    ).first()
    return row[0] if row else None


def _scheduled_at(alert_type: AlertType, now: datetime, timezone: str) -> datetime:
    if alert_type.cadence == AlertCadence.HOURLY:
        return now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)

    tz = ZoneInfo(timezone or "UTC")
    local_now = now.replace(tzinfo=UTC).astimezone(tz)
    local_target = datetime.combine(local_now.date(), time(hour=8), tzinfo=tz)
    if local_now >= local_target:
        local_target += timedelta(days=1)
    return local_target.astimezone(UTC).replace(tzinfo=None)


def _agency_timezone(session: Session, agency_id: int) -> str:
    agency = session.get(Agencies, agency_id)
    return agency.timezone if agency else "UTC"


def _storage_history_name(session: Session, storage_id: int | None) -> str | None:
    storage = session.get(AgencyStorages, storage_id) if storage_id else None
    return storage.history_name if storage else None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _now() -> datetime:
    return utc_now_naive()
