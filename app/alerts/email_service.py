"""Render and send state-driven inventory notification emails."""

from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from flask import current_app, render_template
from loguru import logger
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.auth.location_filters import alert_matches_location_filter, validate_location_filter_ids
from app.auth.models import Agencies, AgencyEmails, AgencyLocations
from app.auth.queries import list_active_emails
from app.inventory.constants import UnknownUpcStatus
from app.inventory.models import ActionLogs, InventoryItemLocationState, Items, UnknownUpcScan
from app.prediction.formatting import rounded_confidence_percent
from app.shared.clock import utc_now_naive
from app.shared.database import get_session
from app.shared.email_addresses import email_domain
from app.shared.email_client import OutboundEmail, send_email
from app.shared.timezone_utils import convert_utc_to_local

from .constants import (
    DISCRETE_EVENT_TYPES,
    IMMEDIATE_EVENT_TYPES,
    LABEL_BY_TYPE,
    PREFERENCE_BY_TYPE,
    AlertSeverity,
    AlertType,
    InventoryAlertEventStatus,
    NotificationDelivery,
    NotificationEmailStatus,
    NotificationKind,
)
from .email_delivery import deliver_notification_email
from .models import InventoryAlertEvent, NotificationEmailDelivery
from .schema import AlertSummaryItem, AlertTableColumn, AlertTableSection, EmailBatch

ERROR_RETRY_DELAY = timedelta(minutes=15)
ACTION_TYPES = {
    AlertType.COUNT_ACTION,
    AlertType.RESTOCK_ACTION,
    AlertType.TAKEOUT_ACTION,
    AlertType.TRANSFER_ACTION,
}
WARNING_TYPES = {
    AlertType.STOCKOUT_FORECAST,
    AlertType.LOW_STOCK,
    AlertType.LOW_STOCK_FORECAST,
    AlertType.STALE_COUNT,
    AlertType.RARE_TAKEOUT,
    AlertType.UNKNOWN_UPC,
}


def process_all_alerts(*, force: bool = False) -> dict[str, int]:
    """Render pending notification deliveries and send due rows."""
    now = _now()
    stats = {"created": 0, "processed": 0, "sent": 0, "failed": 0}
    with get_session() as session:
        stats["created"] = prepare_notification_deliveries(session, now, force=force)
        send_stats = send_due_notification_deliveries(session, now, force=force)
        stats.update(send_stats)
        session.commit()
    logger.info("Notification email run finished", extra=stats | {"force": force})
    return stats


def prepare_notification_deliveries(session: Session, now: datetime | None = None, *, force: bool = False) -> int:
    """Create or refresh pending rendered email deliveries from current state/events."""
    now = now or _now()
    created = 0
    queued_event_ids: set[int] = set()
    for agency in _active_agencies(session):
        for recipient in list_active_emails(agency.id, session, order_by_id=True):
            created += _prepare_recipient_deliveries(session, agency, recipient, now, queued_event_ids, force=force)

    if queued_event_ids:
        events = session.execute(select(InventoryAlertEvent).where(InventoryAlertEvent.id.in_(queued_event_ids))).scalars()
        for event in events:
            if event.status == InventoryAlertEventStatus.PENDING:
                event.status = InventoryAlertEventStatus.QUEUED
                event.queued_at = now
    logger.debug("Notification deliveries prepared", extra={"created_or_updated": created, "queued_event_count": len(queued_event_ids)})
    return created


def send_due_notification_deliveries(session: Session, now: datetime | None = None, *, force: bool = False) -> dict[str, int]:
    """Send due delivery rows once and update delivery status."""
    now = now or _now()
    stats = {"processed": 0, "sent": 0, "failed": 0}
    deliveries = _due_deliveries(session, now, force=force)
    for delivery in deliveries:
        stats["processed"] += 1
        if deliver_notification_email(delivery):
            _mark_delivery_sent(session, delivery, now)
            stats["sent"] += 1
            continue
        _mark_delivery_failed(delivery, now)
        stats["failed"] += 1
    return stats


def _prepare_recipient_deliveries(
    session: Session,
    agency: Agencies,
    recipient: AgencyEmails,
    now: datetime,
    queued_event_ids: set[int],
    *,
    force: bool,
) -> int:
    stock_states = _stock_states_for_recipient(session, recipient)
    events = _events_for_recipient(session, recipient)
    created = 0

    immediate_events = [event for event in events if event.alert_type in IMMEDIATE_EVENT_TYPES]
    if immediate_events:
        created += _upsert_delivery(
            session,
            agency,
            recipient,
            NotificationKind.ALERTS,
            NotificationDelivery.IMMEDIATE,
            _send_at(NotificationDelivery.IMMEDIATE, now, force=force),
            stock_states=[],
            events=immediate_events,
            now=now,
        )
        queued_event_ids.update(event.id for event in immediate_events)

    digest_events = [event for event in events if event.alert_type not in IMMEDIATE_EVENT_TYPES]
    recap_due = _recap_is_due(recipient, agency.timezone, now)
    if recap_due:
        created += _upsert_delivery(
            session,
            agency,
            recipient,
            NotificationKind.RECAPS,
            NotificationDelivery.SCHEDULED,
            now,
            stock_states=stock_states,
            events=digest_events,
            now=now,
        )
        queued_event_ids.update(event.id for event in digest_events)
    elif stock_states or digest_events:
        created += _upsert_delivery(
            session,
            agency,
            recipient,
            NotificationKind.ALERTS,
            NotificationDelivery.SCHEDULED,
            _send_at(NotificationDelivery.SCHEDULED, now, force=force),
            stock_states=stock_states,
            events=digest_events,
            now=now,
        )
        queued_event_ids.update(event.id for event in digest_events)
    return created


def _upsert_delivery(
    session: Session,
    agency: Agencies,
    recipient: AgencyEmails,
    notification_kind: NotificationKind,
    delivery_mode: NotificationDelivery,
    send_at: datetime,
    *,
    stock_states: list[InventoryItemLocationState],
    events: list[InventoryAlertEvent],
    now: datetime,
) -> int:
    batch = _build_batch(session, agency, recipient, notification_kind, delivery_mode, stock_states, events, now)
    if batch is None or not batch.sections:
        return 0

    dedupe_key = _delivery_dedupe_key(notification_kind, delivery_mode, send_at)
    existing = session.scalar(
        select(NotificationEmailDelivery).where(
            NotificationEmailDelivery.agency_id == agency.id,
            NotificationEmailDelivery.agency_email_id == recipient.id,
            NotificationEmailDelivery.dedupe_key == dedupe_key,
        )
    )
    if existing and existing.status == NotificationEmailStatus.SENT:
        return 0

    body_text = render_template("batch_email.txt", batch=batch)
    body_html = render_template("batch_email.html", batch=batch)
    email_delivery = existing or NotificationEmailDelivery(
        agency_id=agency.id,
        agency_email_id=recipient.id,
        recipient_email_snapshot=recipient.email,
        notification_kind=notification_kind,
        delivery=delivery_mode,
        dedupe_key=dedupe_key,
        created_at=now,
    )
    email_delivery.status = NotificationEmailStatus.PENDING
    email_delivery.recipient_email_snapshot = recipient.email
    email_delivery.notification_kind = notification_kind
    email_delivery.delivery = delivery_mode
    email_delivery.send_at = send_at
    email_delivery.next_attempt_at = None
    email_delivery.alert_event_ids_json = [event.id for event in events]
    email_delivery.subject = batch.subject
    email_delivery.preview_text = _preview_text(batch)
    email_delivery.body_html = body_html
    email_delivery.body_text = body_text
    email_delivery.last_error_type = None
    email_delivery.last_error_message = None
    email_delivery.last_error_at = None
    session.add(email_delivery)
    return 1


def _build_batch(
    session: Session,
    agency: Agencies,
    recipient: AgencyEmails,
    notification_kind: NotificationKind,
    delivery_mode: NotificationDelivery,
    stock_states: list[InventoryItemLocationState],
    events: list[InventoryAlertEvent],
    now: datetime,
) -> EmailBatch | None:
    alert_sections = _build_sections(session, stock_states, events, agency.timezone)
    recap_sections = _summary_sections(session, agency, recipient, now) if notification_kind == NotificationKind.RECAPS else []
    sections = [*alert_sections, *recap_sections]
    if notification_kind == NotificationKind.RECAPS and not recap_sections:
        return None
    if not sections:
        return None
    severity = _severity(stock_states, events)
    summary = _summary(stock_states, events)
    has_alerts = bool(alert_sections)
    has_recaps = bool(recap_sections)
    return EmailBatch(
        agency_email=recipient.email,
        agency_name=agency.display_name,
        generated_at=_display_now(agency.timezone, now),
        subject=_subject(agency.display_name, severity["label"], notification_kind, has_alerts=has_alerts),
        title=_title(agency.display_name, notification_kind, has_alerts=has_alerts),
        intro=_intro(notification_kind, delivery_mode, has_alerts=has_alerts, has_recaps=has_recaps),
        severity_label=severity["label"],
        severity_color=severity["color"],
        summary=summary,
        sections=sections,
    )


def _stock_states_for_recipient(session: Session, recipient: AgencyEmails) -> list[InventoryItemLocationState]:
    rows = session.execute(
        select(InventoryItemLocationState)
        .where(
            InventoryItemLocationState.agency_id == recipient.agency_id,
            InventoryItemLocationState.effective_alert_type.is_not(None),
            InventoryItemLocationState.last_counted_at.is_not(None),
        )
        .order_by(
            InventoryItemLocationState.effective_alert_rank.desc(),
            InventoryItemLocationState.effective_severity.desc().nulls_last(),
            InventoryItemLocationState.item_id,
        )
    ).scalars()
    return [state for state in rows if _recipient_allows_state(session, recipient, state)]


def _events_for_recipient(session: Session, recipient: AgencyEmails) -> list[InventoryAlertEvent]:
    rows = session.execute(
        select(InventoryAlertEvent)
        .where(
            InventoryAlertEvent.agency_id == recipient.agency_id,
            InventoryAlertEvent.status == InventoryAlertEventStatus.PENDING,
            InventoryAlertEvent.alert_type.in_(DISCRETE_EVENT_TYPES),
        )
        .order_by(InventoryAlertEvent.event_at, InventoryAlertEvent.id)
    ).scalars()
    return [event for event in rows if _recipient_allows_event(session, recipient, event)]


def _recipient_allows_state(
    session: Session,
    recipient: AgencyEmails,
    state: InventoryItemLocationState,
) -> bool:
    alert_type = state.effective_alert_type
    if alert_type is None or not bool(getattr(recipient, PREFERENCE_BY_TYPE[alert_type])):
        return False
    return _recipient_allows_location(session, recipient, {"agency_location_id": state.agency_location_id})


def _recipient_allows_event(
    session: Session,
    recipient: AgencyEmails,
    event: InventoryAlertEvent,
) -> bool:
    if event.alert_type == AlertType.UNKNOWN_UPC and not _unknown_upc_is_pending(session, event):
        return False
    preference = PREFERENCE_BY_TYPE.get(event.alert_type)
    if preference and not bool(getattr(recipient, preference)):
        return False
    return _recipient_allows_location(session, recipient, event.payload_json)


def _recipient_allows_location(session: Session, recipient: AgencyEmails, payload: dict[str, Any]) -> bool:
    try:
        location_ids = validate_location_filter_ids(session, recipient.agency_id, recipient.location_filter_ids)
    except ValueError as exc:
        logger.warning(
            "Notification recipient skipped because of an invalid location filter",
            extra={"agency_id": recipient.agency_id, "agency_email_id": recipient.id, "error": str(exc)},
        )
        return False
    return alert_matches_location_filter(location_ids, payload)


def _build_sections(
    session: Session,
    stock_states: list[InventoryItemLocationState],
    events: list[InventoryAlertEvent],
    timezone: str,
) -> list[AlertTableSection]:
    item_names = _item_names_for_states(session, stock_states)
    location_names = _location_names_for_states(session, stock_states)
    sections = [
        section
        for section in (
            _stockout_section(stock_states, item_names, location_names, timezone),
            _stockout_forecast_section(stock_states, item_names, location_names),
            _low_stock_section(stock_states, item_names, location_names),
            _low_stock_forecast_section(stock_states, item_names, location_names),
            _stale_count_section(events),
            _rare_takeout_section(events, timezone),
            _scan_activity_section(events, timezone),
            _unknown_upc_section(events, timezone),
        )
        if section is not None
    ]
    return sections


def _stockout_section(
    states: list[InventoryItemLocationState],
    item_names: dict[int, str],
    location_names: dict[int, str],
    timezone: str,
) -> AlertTableSection | None:
    return _stock_section(
        states,
        item_names,
        location_names,
        AlertType.STOCKOUT,
        "Stockouts",
        "Item is at zero or negative quantity for the listed location(s). Restock immediately.",
        [
            AlertTableColumn(key="item_name", label="Item"),
            AlertTableColumn(key="locations", label="Locations"),
            AlertTableColumn(key="current_total", label="Current Total"),
            AlertTableColumn(key="last_activity_at", label="Last Activity"),
        ],
        timezone=timezone,
    )


def _stockout_forecast_section(
    states: list[InventoryItemLocationState],
    item_names: dict[int, str],
    location_names: dict[int, str],
) -> AlertTableSection | None:
    return _stock_section(
        states,
        item_names,
        location_names,
        AlertType.STOCKOUT_FORECAST,
        "Predicted Stockouts",
        "Forecast shows stockout within the configured lead time.",
        [
            AlertTableColumn(key="item_name", label="Item"),
            AlertTableColumn(key="locations", label="Locations"),
            AlertTableColumn(key="lead_time_days", label="Lead Time"),
            AlertTableColumn(key="prediction", label="Prediction"),
            AlertTableColumn(key="confidence", label="Confidence"),
        ],
    )


def _low_stock_section(
    states: list[InventoryItemLocationState],
    item_names: dict[int, str],
    location_names: dict[int, str],
) -> AlertTableSection | None:
    return _stock_section(
        states,
        item_names,
        location_names,
        AlertType.LOW_STOCK,
        "Low Stock",
        "Item is below the configured minimum for the listed location(s).",
        [
            AlertTableColumn(key="item_name", label="Item"),
            AlertTableColumn(key="locations", label="Locations"),
            AlertTableColumn(key="current_total", label="Current Total"),
            AlertTableColumn(key="min_quantity", label="Minimum"),
        ],
    )


def _low_stock_forecast_section(
    states: list[InventoryItemLocationState],
    item_names: dict[int, str],
    location_names: dict[int, str],
) -> AlertTableSection | None:
    return _stock_section(
        states,
        item_names,
        location_names,
        AlertType.LOW_STOCK_FORECAST,
        "Predicted Low Stock",
        "Forecast shows the item reaching minimum within the configured lead time.",
        [
            AlertTableColumn(key="item_name", label="Item"),
            AlertTableColumn(key="locations", label="Locations"),
            AlertTableColumn(key="lead_time_days", label="Lead Time"),
            AlertTableColumn(key="prediction", label="Prediction"),
            AlertTableColumn(key="confidence", label="Confidence"),
        ],
    )


def _stock_section(
    states: list[InventoryItemLocationState],
    item_names: dict[int, str],
    location_names: dict[int, str],
    alert_type: AlertType,
    title: str,
    note: str,
    columns: list[AlertTableColumn],
    *,
    timezone: str = "UTC",
) -> AlertTableSection | None:
    rows = [_stock_row(state, item_names, location_names, timezone) for state in states if state.effective_alert_type == alert_type]
    if not rows:
        return None
    return AlertTableSection(title=title, note=note, columns=columns, rows=rows)


def _stock_row(
    state: InventoryItemLocationState,
    item_names: dict[int, str],
    location_names: dict[int, str],
    timezone: str,
) -> dict[str, str | int | float | None]:
    return {
        "item_name": item_names.get(state.item_id, str(state.item_id)),
        "locations": location_names.get(state.agency_location_id, str(state.agency_location_id)),
        "current_total": _total(state.total_quantity),
        "min_quantity": state.min_quantity_snapshot,
        "lead_time_days": _days(state.lead_time_days_snapshot),
        "prediction": _state_prediction(state),
        "confidence": _confidence(state.confidence_percent),
        "last_activity_at": _display_datetime(_iso(state.last_activity_at), timezone),
    }


def _item_names_for_states(session: Session, states: list[InventoryItemLocationState]) -> dict[int, str]:
    item_ids = {state.item_id for state in states}
    if not item_ids:
        return {}
    rows = session.execute(select(Items.id, Items.name).where(Items.id.in_(item_ids))).tuples().all()
    return dict(rows)


def _location_names_for_states(session: Session, states: list[InventoryItemLocationState]) -> dict[int, str]:
    location_ids = {state.agency_location_id for state in states}
    if not location_ids:
        return {}
    rows = session.execute(select(AgencyLocations.id, AgencyLocations.name).where(AgencyLocations.id.in_(location_ids))).tuples().all()
    return dict(rows)


def _stale_count_section(events: list[InventoryAlertEvent]) -> AlertTableSection | None:
    rows = [
        {
            "item_name": event.payload_json.get("item_name"),
            "location_name": event.payload_json.get("location_name"),
            "days_since_last_count": event.payload_json.get("days_since_last_count") or "Never",
            "current_total": _total(event.payload_json.get("current_total")),
        }
        for event in events
        if event.alert_type == AlertType.STALE_COUNT
    ]
    return _simple_section(
        "Stale Counts",
        "Count these item/location pairs before the next incoming delivery or vendor restock.",
        rows,
        [
            "item_name:Item",
            "location_name:Location",
            "days_since_last_count:Days Since Last Count",
            "current_total:Current Count",
        ],
    )


def _rare_takeout_section(events: list[InventoryAlertEvent], timezone: str) -> AlertTableSection | None:
    rows = [
        {
            "item_name": event.payload_json.get("item_name"),
            "location_name": event.payload_json.get("location_name"),
            "days_since_last_takeout": event.payload_json.get("days_since_last_takeout"),
            "last_takeout_at": _display_datetime(event.payload_json.get("last_takeout_at"), timezone),
            "current_total": _total(event.payload_json.get("current_total")),
        }
        for event in events
        if event.alert_type == AlertType.RARE_TAKEOUT
    ]
    return _simple_section(
        "Rare Takeouts",
        "Takeout activity is unusual for this item/location.",
        rows,
        [
            "item_name:Item",
            "location_name:Location",
            "days_since_last_takeout:Days Since Last Takeout",
            "last_takeout_at:Last Takeout At",
            "current_total:Current Count",
        ],
    )


def _scan_activity_section(events: list[InventoryAlertEvent], timezone: str) -> AlertTableSection | None:
    rows = [
        {
            "item_name": event.payload_json.get("item_name"),
            "scan_type": _scan_type(event.payload_json),
            "quantity": event.payload_json.get("quantity"),
            "admin_action": "Yes" if event.payload_json.get("admin_action") else "No",
            "time_scanned": _display_datetime(event.payload_json.get("time_scanned"), timezone),
        }
        for event in events
        if event.alert_type in ACTION_TYPES
    ]
    return _simple_section(
        "Scan Activity",
        "Configured count, restock, takeout, and transfer notifications.",
        rows,
        [
            "item_name:Item",
            "scan_type:Scan Type",
            "quantity:Quantity",
            "admin_action:Admin?",
            "time_scanned:Time Scanned",
        ],
    )


def _unknown_upc_section(events: list[InventoryAlertEvent], timezone: str) -> AlertTableSection | None:
    rows = [
        {
            "upc": event.payload_json.get("upc"),
            "lookup_title": event.payload_json.get("lookup_title") or "Not found",
            "created_at": _display_datetime(event.payload_json.get("created_at"), timezone),
        }
        for event in events
        if event.alert_type == AlertType.UNKNOWN_UPC
    ]
    return _simple_section(
        "Unknown UPCs",
        "These UPCs need admin review before they can scan to an item.",
        rows,
        ["upc:UPC", "lookup_title:Lookup Name", "created_at:First Seen"],
    )


def _simple_section(
    title: str,
    note: str,
    rows: list[dict[str, Any]],
    column_specs: list[str],
) -> AlertTableSection | None:
    if not rows:
        return None
    columns = [AlertTableColumn(key=spec.split(":", 1)[0], label=spec.split(":", 1)[1]) for spec in column_specs]
    return AlertTableSection(title=title, note=note, columns=columns, rows=rows)


def _summary_sections(
    session: Session,
    agency: Agencies,
    recipient: AgencyEmails,
    now: datetime,
) -> list[AlertTableSection]:
    local_now = _local_now(agency.timezone, now)
    sections: list[AlertTableSection] = []
    for report_type, enabled, bounds in (
        ("Daily", recipient.daily_summary, _prior_day_bounds(local_now)),
        ("Weekly", recipient.weekly_summary and local_now.weekday() == 0, _prior_week_bounds(local_now)),
        ("Monthly", recipient.monthly_summary and local_now.day == 1, _prior_month_bounds(local_now)),
        ("Yearly", recipient.yearly_summary and local_now.month == 1 and local_now.day == 1, _prior_year_bounds(local_now)),
    ):
        if enabled and (section := _summary_section(session, agency.id, report_type, bounds)):
            sections.append(section)
    return sections


def _summary_section(
    session: Session,
    agency_id: int,
    report_type: str,
    bounds: tuple[datetime, datetime],
) -> AlertTableSection | None:
    start_at, end_at = bounds
    rows = session.execute(
        select(
            ActionLogs.operation_type,
            func.count(ActionLogs.id),
            func.coalesce(func.sum(ActionLogs.quantity_delta), 0),
        )
        .where(ActionLogs.agency_id == agency_id, ActionLogs.time_scanned >= start_at, ActionLogs.time_scanned < end_at)
        .group_by(ActionLogs.operation_type)
        .order_by(ActionLogs.operation_type)
    ).all()
    return _simple_section(
        f"{report_type} Summary",
        f"{report_type} scan totals for the completed reporting period.",
        [
            {
                "operation_type": operation.value.title(),
                "scan_count": scan_count,
                "quantity_total": quantity_total,
            }
            for operation, scan_count, quantity_total in rows
        ],
        ["operation_type:Operation", "scan_count:Scans", "quantity_total:Quantity"],
    )


def _due_deliveries(session: Session, now: datetime, *, force: bool) -> list[NotificationEmailDelivery]:
    filters = []
    if not force:
        filters.append(
            or_(
                ((NotificationEmailDelivery.status == NotificationEmailStatus.PENDING) & (NotificationEmailDelivery.send_at <= now)),
                (
                    (NotificationEmailDelivery.status == NotificationEmailStatus.ERROR)
                    & (func.coalesce(NotificationEmailDelivery.next_attempt_at, NotificationEmailDelivery.send_at) <= now)
                ),
            )
        )
    else:
        filters.append(NotificationEmailDelivery.status.in_([NotificationEmailStatus.PENDING, NotificationEmailStatus.ERROR]))
    return list(
        session.execute(select(NotificationEmailDelivery).where(*filters).order_by(NotificationEmailDelivery.send_at, NotificationEmailDelivery.id))
        .scalars()
        .all()
    )


def _mark_delivery_sent(session: Session, delivery: NotificationEmailDelivery, now: datetime) -> None:
    delivery.status = NotificationEmailStatus.SENT
    delivery.sent_at = now
    delivery.last_error_type = None
    delivery.last_error_message = None
    delivery.last_error_at = None
    if delivery.alert_event_ids_json:
        events = session.execute(select(InventoryAlertEvent).where(InventoryAlertEvent.id.in_(delivery.alert_event_ids_json))).scalars()
        for event in events:
            if event.status in {InventoryAlertEventStatus.PENDING, InventoryAlertEventStatus.QUEUED}:
                event.status = InventoryAlertEventStatus.NOTIFIED
                event.notified_at = now


def _mark_delivery_failed(delivery: NotificationEmailDelivery, now: datetime) -> None:
    delivery.status = NotificationEmailStatus.ERROR
    delivery.attempt_count = int(delivery.attempt_count or 0) + 1
    delivery.last_error_type = "EMAIL_DELIVERY_FAILED"
    delivery.last_error_message = "Email provider did not accept the notification delivery."
    delivery.last_error_at = now
    delivery.next_attempt_at = max(delivery.send_at, now + ERROR_RETRY_DELAY)
    _send_developer_delivery_failure_alert(delivery)


def _send_developer_delivery_failure_alert(delivery: NotificationEmailDelivery) -> None:
    admin_email = str(current_app.config.get("ADMIN_ALERT_EMAIL") or "").strip()
    if not admin_email:
        return
    body = (
        "Urgent Inventory IQ email delivery failure\n\n"
        "Check Railway logs and the notification_email_deliveries table.\n\n"
        f"Delivery ID: {delivery.id}\n"
        f"Agency ID: {delivery.agency_id}\n"
        f"Agency Email ID: {delivery.agency_email_id}\n"
        f"Recipient Domain: {email_domain(delivery.recipient_email_snapshot)}\n"
        f"Notification Kind: {delivery.notification_kind.value}\n"
        f"Delivery: {delivery.delivery.value}\n"
        f"Attempt Count: {delivery.attempt_count}\n"
        f"Next Attempt At: {delivery.next_attempt_at}\n"
        f"Error Type: {delivery.last_error_type}\n"
    )
    sent = send_email(
        OutboundEmail(
            subject="[URGENT] Inventory IQ email delivery failure",
            text_body=body,
            to_email=admin_email,
        ),
        retry_delays_seconds=(),
    )
    if not sent:
        logger.error(
            "Developer delivery failure alert email failed",
            extra={"notification_email_delivery_id": delivery.id, "agency_id": delivery.agency_id},
        )


def _active_agencies(session: Session) -> list[Agencies]:
    return list(session.execute(select(Agencies).where(Agencies.active.is_(True)).order_by(Agencies.id)).scalars().all())


def _unknown_upc_is_pending(session: Session, event: InventoryAlertEvent) -> bool:
    unknown_upc_id = event.payload_json.get("unknown_upc_id")
    if isinstance(unknown_upc_id, int):
        return (
            session.scalar(
                select(UnknownUpcScan.status).where(
                    UnknownUpcScan.agency_id == event.agency_id,
                    UnknownUpcScan.id == unknown_upc_id,
                )
            )
            == UnknownUpcStatus.PENDING
        )
    return False


def _summary(stock_states: list[InventoryItemLocationState], events: list[InventoryAlertEvent]) -> list[AlertSummaryItem]:
    counts = Counter([state.effective_alert_type for state in stock_states if state.effective_alert_type] + [event.alert_type for event in events])
    return [AlertSummaryItem(label=LABEL_BY_TYPE[alert_type], count=count) for alert_type, count in counts.items() if count > 0]


def _severity(stock_states: list[InventoryItemLocationState], events: list[InventoryAlertEvent]) -> dict[str, str]:
    if any(state.effective_alert_type == AlertType.STOCKOUT for state in stock_states):
        return {"label": "Critical", "color": "#9F1F1F"}
    if any(state.effective_severity in {AlertSeverity.CRITICAL, AlertSeverity.HIGH, AlertSeverity.WARNING} for state in stock_states) or any(
        event.alert_type in WARNING_TYPES for event in events
    ):
        return {"label": "Warning", "color": "#8A5A00"}
    return {"label": "Activity", "color": "#2F6B4F"}


def _subject(agency_name: str, severity_label: str, notification_kind: NotificationKind, *, has_alerts: bool) -> str:
    prefix = {
        "Critical": "[CRITICAL]",
        "Warning": "[WARNING]",
        "Activity": "[ACTIVITY]",
    }[severity_label]
    if notification_kind == NotificationKind.RECAPS and has_alerts:
        return f"{prefix} Inventory Alerts and Periodic Recap - {agency_name}"
    if notification_kind == NotificationKind.RECAPS:
        return f"Inventory Periodic Recap - {agency_name}"
    return f"{prefix} Inventory Alerts - {agency_name}"


def _title(agency_name: str, notification_kind: NotificationKind, *, has_alerts: bool) -> str:
    if notification_kind == NotificationKind.RECAPS and has_alerts:
        return f"Inventory Alerts and Periodic Recap - {agency_name}"
    if notification_kind == NotificationKind.RECAPS:
        return f"Inventory Periodic Recap - {agency_name}"
    return f"Inventory Alerts - {agency_name}"


def _intro(
    notification_kind: NotificationKind,
    delivery_mode: NotificationDelivery,
    *,
    has_alerts: bool,
    has_recaps: bool,
) -> str:
    if notification_kind == NotificationKind.RECAPS and has_alerts and has_recaps:
        return "This email includes current inventory alerts first, followed by your periodic recap."
    if notification_kind == NotificationKind.RECAPS:
        return "This email includes your periodic inventory recap."
    if delivery_mode == NotificationDelivery.IMMEDIATE:
        return "This email includes alert activity configured for immediate notification."
    return "This email includes grouped inventory alerts scheduled for review."


def _preview_text(batch: EmailBatch) -> str:
    if not batch.summary:
        return "Inventory IQ notification update."
    parts = [f"{item.count} {item.label}" for item in batch.summary[:3]]
    return ", ".join(parts)[:255]


def _delivery_dedupe_key(notification_kind: NotificationKind, delivery_mode: NotificationDelivery, send_at: datetime) -> str:
    if delivery_mode == NotificationDelivery.IMMEDIATE:
        stamp = send_at.strftime("%Y-%m-%dT%H:%M")
    elif notification_kind == NotificationKind.ALERTS:
        stamp = send_at.strftime("%Y-%m-%dT%H")
    else:
        stamp = send_at.strftime("%Y-%m-%d")
    return f"{notification_kind.value}:{delivery_mode.value}:{stamp}"


def _send_at(delivery_mode: NotificationDelivery, now: datetime, *, force: bool) -> datetime:
    if force:
        return now
    if delivery_mode == NotificationDelivery.IMMEDIATE:
        return now
    return _round_up_hour(now)


def _round_up_hour(value: datetime) -> datetime:
    rounded = value.replace(minute=0, second=0, microsecond=0)
    if rounded < value:
        rounded += timedelta(hours=1)
    return rounded


def _display_now(timezone: str, now: datetime) -> str:
    local = convert_utc_to_local(now, timezone) or now
    return _format_local_datetime(local)


def _display_datetime(value: Any, timezone: str) -> str:
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return str(value).replace("T", " ").split(".", maxsplit=1)[0]
    local = convert_utc_to_local(parsed, timezone) or parsed
    return _format_local_datetime(local)


def _format_local_datetime(value: datetime) -> str:
    return value.strftime("%B %d, %Y %H:%M")


def _total(value: Any) -> str:
    return f"{value} total"


def _days(value: Any) -> str:
    return "" if value is None else f"{value} days"


def _state_prediction(state: InventoryItemLocationState) -> str | None:
    if state.effective_alert_type == AlertType.STOCKOUT_FORECAST and state.days_until_stockout is not None:
        return f"{state.days_until_stockout} days until stockout"
    if state.effective_alert_type == AlertType.LOW_STOCK_FORECAST and state.days_until_low is not None:
        return f"{state.days_until_low} days until low"
    return None


def _confidence(value: Any) -> str:
    rounded = rounded_confidence_percent(value)
    return "" if rounded is None else f"{rounded}%"


def _scan_type(payload: dict[str, Any]) -> str:
    operation = str(payload.get("operation_type", "")).title()
    from_name = payload.get("from_location_name")
    to_name = payload.get("to_location_name")
    if from_name and to_name:
        return f"{operation} {from_name} -> {to_name}"
    if from_name:
        return f"{operation} from {from_name}"
    if to_name:
        return f"{operation} to {to_name}"
    return operation


def _now() -> datetime:
    return utc_now_naive()


def _recap_is_due(recipient: AgencyEmails, timezone: str, now: datetime) -> bool:
    local_now = _local_now(timezone, now)
    has_recap_enabled = any((recipient.daily_summary, recipient.weekly_summary, recipient.monthly_summary, recipient.yearly_summary))
    if not has_recap_enabled:
        return False
    return _is_daily_email_window(timezone, now) and any(
        (
            recipient.daily_summary,
            recipient.weekly_summary and local_now.weekday() == 0,
            recipient.monthly_summary and local_now.day == 1,
            recipient.yearly_summary and local_now.month == 1 and local_now.day == 1,
        )
    )


def _is_daily_email_window(timezone: str, now: datetime) -> bool:
    local = _local_now(timezone, now)
    return local.hour == 8


def _local_now(timezone: str, now: datetime) -> datetime:
    aware = now.replace(tzinfo=UTC) if now.tzinfo is None else now
    return aware.astimezone(ZoneInfo(timezone or "UTC"))


def _prior_day_bounds(local_now: datetime) -> tuple[datetime, datetime]:
    end_local = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    return _utc_naive(end_local - timedelta(days=1)), _utc_naive(end_local)


def _prior_week_bounds(local_now: datetime) -> tuple[datetime, datetime]:
    end_local = (local_now - timedelta(days=local_now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    return _utc_naive(end_local - timedelta(days=7)), _utc_naive(end_local)


def _prior_month_bounds(local_now: datetime) -> tuple[datetime, datetime]:
    end_local = local_now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    previous_month = (end_local - timedelta(days=1)).replace(day=1)
    return _utc_naive(previous_month), _utc_naive(end_local)


def _prior_year_bounds(local_now: datetime) -> tuple[datetime, datetime]:
    end_local = local_now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    return _utc_naive(end_local.replace(year=end_local.year - 1)), _utc_naive(end_local)


def _utc_naive(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(tzinfo=None)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None
