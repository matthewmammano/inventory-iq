"""Alert generation and state sync."""

from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.location_filters import alert_matches_location_filter, validate_location_filter_ids
from app.auth.models import Agencies, AgencyEmails, AgencyLocations, AgencyStorages
from app.inventory.constants import OperationType
from app.inventory.item_queries import get_agency_item, list_items
from app.inventory.models import ActionLogs, Items
from app.prediction.estimator import (
    days_to_threshold,
    effective_lead_time_days,
    get_location_item_quantity,
    project_location_item,
)
from app.prediction.segments import get_location_storage_ids
from app.shared.clock import utc_now_naive

from .constants import ALERT_RESEND_SUPPRESSION_DAYS, AlertAction, AlertType
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
CONDITION_ALERT_ACTIONS = (AlertAction.PENDING, AlertAction.SUPPRESSED, AlertAction.SENT)

PREFERENCE_BY_TYPE = {
    AlertType.STOCKOUT: "alert_for_stockout",
    AlertType.STOCKOUT_PRED: "alert_for_stockout_pred",
    AlertType.LOW: "alert_for_low",
    AlertType.LOW_PRED: "alert_for_low_pred",
    AlertType.STALE_COUNT: "alert_for_stale_count",
    AlertType.RARE_TAKEOUT: "alert_for_rare_takeout",
    AlertType.COUNT_ACTION: "alert_for_count",
    AlertType.RESTOCK_ACTION: "alert_for_restock",
    AlertType.TAKEOUT_ACTION: "alert_for_takeout",
    AlertType.TRANSFER_ACTION: "alert_for_transfer",
}


def record_action_log_alerts(
    session: Session,
    action_logs: list[ActionLogs],
) -> None:
    """Create recipient-specific scan activity, stock, prediction, and rare-takeout alerts."""
    if not action_logs:
        return

    now = _now()
    for action in action_logs:
        _record_scan_activity(session, action, now)
        _sync_action_rare_takeout_alert(session, action, now)

    for agency_id, item_id, location_id in _affected_item_locations(session, action_logs):
        agency = session.get(Agencies, agency_id)
        item = get_agency_item(agency_id, item_id, session=session)
        if agency and agency.active and item:
            _sync_stock_alerts(session, agency, item, location_id, now, include_predictions=True)


def generate_scheduled_alerts(session: Session, agency_id: int | None = None) -> int:
    """Generate daily audit alerts for active agencies."""
    now = _now()
    stmt = select(Agencies).where(Agencies.active.is_(True))
    if agency_id is not None:
        stmt = stmt.where(Agencies.id == agency_id)

    count = 0
    agencies = list(session.execute(stmt).scalars().all())
    if agency_id is not None and not agencies:
        logger.warning(
            "Scheduled alert audit found no active agency",
            extra={"agency_id": agency_id},
        )

    for agency in agencies:
        agency_count = 0
        for location in agency.locations:
            for item in list_items(agency.id, session=session):
                _sync_stock_alerts(session, agency, item, location.id, now, include_predictions=True)
                _sync_stale_count_alert(session, agency, item, location, now)
                _sync_rare_takeout_alert(session, agency, item, location, now)
                count += 1
                agency_count += 1
        session.flush()
        action_counts = _alert_action_counts(session, agency.id)
        pending_type_counts = _pending_alert_type_counts(session, agency.id)
        logger.info(
            "Daily inventory alert audit checked agency: "
            f"item_location_checks={agency_count} "
            f"alert_record_actions={_format_counts(action_counts)} "
            f"pending_alert_types={_format_counts(pending_type_counts)}",
            extra={
                "agency_id": agency.id,
                "agency_name": agency.display_name,
                "rows_checked": agency_count,
                "action_counts": dict(action_counts),
                "pending_type_counts": dict(pending_type_counts),
            },
        )

    logger.info(
        "Daily inventory alert audit finished",
        extra={"agency_id": agency_id, "item_location_checks": count},
    )
    return count


def _record_scan_activity(session: Session, action: ActionLogs, now: datetime) -> None:
    alert_type = ACTION_ALERT_TYPES.get(action.operation_type)
    if alert_type is None or action.item_id is None:
        return

    item = _action_item(session, action)
    if item is None:
        return
    details = {
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
    _upsert_alert(session, action.agency_id, alert_type, details, now)


def _sync_action_rare_takeout_alert(
    session: Session,
    action: ActionLogs,
    now: datetime,
) -> None:
    if action.operation_type != OperationType.TAKEOUT or action.item_id is None:
        return
    storage = session.get(AgencyStorages, action.from_location_id) if action.from_location_id else None
    agency = session.get(Agencies, action.agency_id)
    item = _action_item(session, action)
    if (
        not storage
        or storage.agency_id != action.agency_id
        or not storage.location
        or not agency
        or not agency.active
        or not item
        or not action.time_scanned
    ):
        return
    _sync_rare_takeout_alert(
        session,
        agency,
        item,
        storage.location,
        now,
        before_time=action.time_scanned,
    )


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
    identity = _stock_identity(item.id, agency_location_id)

    for alert_type in STOCK_PRIORITY:
        if alert_type not in active_types:
            _resolve_matching_condition(session, agency.id, alert_type, identity, now)
    for recipient in _stock_alert_recipients(session, agency.id, location.id):
        top_type = next(
            (alert_type for alert_type in STOCK_PRIORITY if alert_type in active_types and _recipient_enabled(recipient, alert_type)),
            None,
        )
        if top_type is None:
            continue

        for alert_type in active_types:
            if alert_type not in STOCK_PRIORITY or not _recipient_enabled(recipient, alert_type):
                continue
            action = AlertAction.PENDING if alert_type == top_type else AlertAction.SUPPRESSED
            _upsert_recipient_alert(
                session,
                recipient.id,
                agency.id,
                alert_type,
                details_by_type[alert_type],
                now,
                desired_action=action,
            )


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
    effective_trend = -projection.daily_usage
    days_stockout = days_to_threshold(projection.current_quantity, effective_trend, 0)
    days_low = days_to_threshold(projection.current_quantity, effective_trend, min_quantity)
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
        _resolve_matching_condition(session, agency.id, AlertType.STALE_COUNT, identity, now)
        return

    last_counted = _last_location_action_at(session, agency.id, item.id, location.id, OperationType.COUNT)
    days_since = None if last_counted is None else (now.date() - last_counted.date()).days
    if days_since is not None and days_since < days:
        _resolve_matching_condition(session, agency.id, AlertType.STALE_COUNT, identity, now)
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
    *,
    before_time: datetime | None = None,
) -> None:
    days = int(agency.alert_rare_scan_days or 0)
    identity = _stock_identity(item.id, location.id)
    if days <= 0:
        _resolve_matching_condition(session, agency.id, AlertType.RARE_TAKEOUT, identity, now)
        return

    last_takeout = _last_location_action_at(session, agency.id, item.id, location.id, OperationType.TAKEOUT, before_time=before_time)
    if last_takeout is None:
        _resolve_matching_condition(session, agency.id, AlertType.RARE_TAKEOUT, identity, now)
        return

    days_since = (now.date() - last_takeout.date()).days
    if days_since < days:
        _resolve_matching_condition(session, agency.id, AlertType.RARE_TAKEOUT, identity, now)
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
) -> list[AlertRecords]:
    rows: list[AlertRecords] = []
    for recipient in _enabled_recipients(session, agency_id, alert_type, details):
        rows.append(
            _upsert_recipient_alert(
                session,
                recipient.id,
                agency_id,
                alert_type,
                details,
                now,
                desired_action=desired_action,
            )
        )
    return rows


def _upsert_recipient_alert(
    session: Session,
    agency_email_id: int,
    agency_id: int,
    alert_type: AlertType,
    details: dict[str, Any],
    now: datetime,
    *,
    desired_action: AlertAction,
) -> AlertRecords:
    identity = _identity(alert_type, details)
    existing = _find_open_alert(session, agency_id, agency_email_id, alert_type, identity)
    action = _dedupe_action(session, agency_id, agency_email_id, alert_type, identity, desired_action, now)
    if existing is None:
        alert = AlertRecords(
            agency_id=agency_id,
            agency_email_id=agency_email_id,
            type=alert_type,
            action=action,
            details_json=details,
            created_at=now,
            action_at=now,
        )
        session.add(alert)
        return alert

    existing.details_json = details
    if existing.action != action:
        existing.action = action
        existing.action_at = now
    return existing


def _dedupe_action(
    session: Session,
    agency_id: int,
    agency_email_id: int,
    alert_type: AlertType,
    identity: dict[str, Any],
    desired_action: AlertAction,
    now: datetime,
) -> AlertAction:
    if desired_action != AlertAction.PENDING:
        return desired_action
    if _recently_sent(session, agency_id, agency_email_id, alert_type, identity, now):
        return AlertAction.SUPPRESSED
    return desired_action


def _recently_sent(
    session: Session,
    agency_id: int,
    agency_email_id: int,
    alert_type: AlertType,
    identity: dict[str, Any],
    now: datetime,
) -> bool:
    since = now - timedelta(days=ALERT_RESEND_SUPPRESSION_DAYS)
    stmt = (
        select(AlertRecords)
        .where(
            AlertRecords.agency_id == agency_id,
            AlertRecords.agency_email_id == agency_email_id,
            AlertRecords.type == alert_type,
            AlertRecords.action == AlertAction.SENT,
            AlertRecords.action_at >= since,
        )
        .order_by(AlertRecords.action_at.desc())
    )
    sent = next(
        (alert for alert in session.execute(stmt).scalars() if _identity(alert_type, alert.details_json) == identity),
        None,
    )
    return sent is not None


def _resolve_matching_condition(
    session: Session,
    agency_id: int,
    alert_type: AlertType,
    identity: dict[str, Any],
    now: datetime,
) -> None:
    for alert in _find_condition_alerts(session, agency_id, alert_type, identity):
        action = AlertAction.RESOLVED if alert.action == AlertAction.SENT else AlertAction.CLEARED
        if alert.action != action:
            alert.action = action
            alert.action_at = now


def _find_open_alert(
    session: Session,
    agency_id: int,
    agency_email_id: int,
    alert_type: AlertType,
    identity: dict[str, Any],
) -> AlertRecords | None:
    return next(
        iter(_find_open_alerts(session, agency_id, alert_type, identity, agency_email_id)),
        None,
    )


def _find_open_alerts(
    session: Session,
    agency_id: int,
    alert_type: AlertType,
    identity: dict[str, Any],
    agency_email_id: int | None = None,
) -> list[AlertRecords]:
    filters = [
        AlertRecords.agency_id == agency_id,
        AlertRecords.type == alert_type,
        AlertRecords.action.in_(OPEN_ALERT_ACTIONS),
    ]
    if agency_email_id is not None:
        filters.append(AlertRecords.agency_email_id == agency_email_id)
    alerts = session.execute(select(AlertRecords).where(*filters)).scalars()
    return [alert for alert in alerts if _identity(alert_type, alert.details_json) == identity]


def _find_condition_alerts(
    session: Session,
    agency_id: int,
    alert_type: AlertType,
    identity: dict[str, Any],
) -> list[AlertRecords]:
    alerts = session.execute(
        select(AlertRecords).where(
            AlertRecords.agency_id == agency_id,
            AlertRecords.type == alert_type,
            AlertRecords.action.in_(CONDITION_ALERT_ACTIONS),
        )
    ).scalars()
    return [alert for alert in alerts if _identity(alert_type, alert.details_json) == identity]


def _identity(alert_type: AlertType, details: dict[str, Any]) -> dict[str, Any]:
    if alert_type in ACTION_ALERT_TYPES.values():
        return {"action_log_id": details.get("action_log_id")}
    return _stock_identity(details.get("item_id"), details.get("agency_location_id"))


def _stock_identity(item_id: int | None, agency_location_id: int | None) -> dict[str, Any]:
    return {"item_id": item_id, "agency_location_id": agency_location_id}


def _affected_item_locations(session: Session, action_logs: list[ActionLogs]) -> set[tuple[int, int, int]]:
    pairs: set[tuple[int, int, int]] = set()
    for action in action_logs:
        if action.item_id is None:
            continue
        for storage_id in (action.from_location_id, action.to_location_id):
            storage = session.get(AgencyStorages, storage_id) if storage_id else None
            if storage and storage.agency_id == action.agency_id:
                pairs.add((action.agency_id, action.item_id, storage.location_id))
    return pairs


def _last_location_action_at(
    session: Session,
    agency_id: int,
    item_id: int,
    agency_location_id: int,
    operation_type: OperationType,
    *,
    before_time: datetime | None = None,
) -> datetime | None:
    storage_ids = get_location_storage_ids(session, agency_id, agency_location_id)
    if not storage_ids:
        return None
    column = ActionLogs.from_location_id if operation_type == OperationType.TAKEOUT else ActionLogs.to_location_id
    stmt = select(ActionLogs.time_scanned).where(
        ActionLogs.agency_id == agency_id,
        ActionLogs.item_id == item_id,
        ActionLogs.operation_type == operation_type,
        column.in_(storage_ids),
    )
    if before_time is not None:
        stmt = stmt.where(ActionLogs.time_scanned < before_time)
    row = session.execute(stmt.order_by(ActionLogs.time_scanned.desc()).limit(1)).first()
    return row[0] if row else None


def _enabled_recipients(
    session: Session,
    agency_id: int,
    alert_type: AlertType,
    details: dict[str, Any],
) -> list[AgencyEmails]:
    preference = PREFERENCE_BY_TYPE[alert_type]
    recipients = session.execute(select(AgencyEmails).where(AgencyEmails.agency_id == agency_id).order_by(AgencyEmails.id)).scalars()
    return [recipient for recipient in recipients if bool(getattr(recipient, preference)) and _recipient_allows_alert(session, recipient, details)]


def _stock_alert_recipients(session: Session, agency_id: int, agency_location_id: int) -> list[AgencyEmails]:
    details = {"agency_location_id": agency_location_id}
    recipients = session.execute(select(AgencyEmails).where(AgencyEmails.agency_id == agency_id).order_by(AgencyEmails.id)).scalars()
    return [
        recipient
        for recipient in recipients
        if any(_recipient_enabled(recipient, alert_type) for alert_type in STOCK_PRIORITY) and _recipient_allows_alert(session, recipient, details)
    ]


def _recipient_enabled(recipient: AgencyEmails, alert_type: AlertType) -> bool:
    return bool(getattr(recipient, PREFERENCE_BY_TYPE[alert_type]))


def _recipient_allows_alert(
    session: Session,
    recipient: AgencyEmails,
    details: dict[str, Any],
) -> bool:
    try:
        location_ids = validate_location_filter_ids(session, recipient.agency_id, recipient.location_filter_ids)
    except ValueError as exc:
        logger.warning(
            f"Alert recipient has invalid location filter: agency_email_id={recipient.id}",
            extra={
                "agency_id": recipient.agency_id,
                "agency_email_id": recipient.id,
                "error": str(exc),
            },
        )
        return False
    return alert_matches_location_filter(location_ids, details)


def _alert_action_counts(session: Session, agency_id: int) -> Counter[str]:
    rows = session.execute(select(AlertRecords.action, func.count()).where(AlertRecords.agency_id == agency_id).group_by(AlertRecords.action)).all()
    return Counter({action.value: count for action, count in rows})


def _pending_alert_type_counts(session: Session, agency_id: int) -> Counter[str]:
    rows = session.execute(
        select(AlertRecords.type, func.count())
        .where(
            AlertRecords.agency_id == agency_id,
            AlertRecords.action == AlertAction.PENDING,
        )
        .group_by(AlertRecords.type)
    ).all()
    return Counter({alert_type.value: count for alert_type, count in rows})


def _format_counts(counts: Counter[str]) -> str:
    if not counts:
        return "none"
    return ", ".join(f"{key}={counts[key]}" for key in sorted(counts))


def _action_item(session: Session, action: ActionLogs) -> Items | None:
    if action.item and action.item.agency_id == action.agency_id and action.item.active:
        return action.item
    if action.item_id is None:
        return None
    return get_agency_item(action.agency_id, action.item_id, session=session)


def _storage_history_name(session: Session, agency_id: int, storage_id: int | None) -> str | None:
    storage = session.get(AgencyStorages, storage_id) if storage_id else None
    return storage.history_name if storage and storage.agency_id == agency_id else None


def _storage_location_id(session: Session, agency_id: int, storage_id: int | None) -> int | None:
    storage = session.get(AgencyStorages, storage_id) if storage_id else None
    return storage.location_id if storage and storage.agency_id == agency_id else None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _now() -> datetime:
    return utc_now_naive()
