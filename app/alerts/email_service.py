"""Render and send state-driven inventory notification emails."""

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from enum import StrEnum
from typing import Any
from zoneinfo import ZoneInfo

from flask import current_app, render_template
from loguru import logger
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.auth.location_filters import alert_matches_location_filter, validate_location_filter_ids
from app.auth.models import Agencies, AgencyEmails, AgencyLocations
from app.auth.notification_preferences import AlertEmailFrequency, NotificationPreference, due_summary_preferences
from app.auth.queries import list_active_emails
from app.inventory.constants import UnknownUpcStatus
from app.inventory.models import ActionLogs, InventoryItemLocationState, Items, UnknownUpcScan
from app.prediction.formatting import rounded_confidence_percent
from app.shared.clock import utc_now_naive
from app.shared.database import get_session
from app.shared.email_addresses import email_domain
from app.shared.email_client import OutboundEmail, send_email
from app.shared.email_subjects import INVENTORY_SUMMARIES_TITLE, inventory_summary_title, report_subject
from app.shared.timezone_utils import convert_utc_to_local

from .constants import (
    DISCRETE_EVENT_TYPES,
    IMMEDIATE_EVENT_TYPES,
    LABEL_BY_TYPE,
    PREFERENCE_BY_TYPE,
    SEVERITY_ORDER,
    AlertSeverity,
    AlertType,
    InventoryAlertEventStatus,
    NotificationDeliveryKind,
    NotificationEmailStatus,
)
from .email_delivery import deliver_notification_email
from .models import InventoryAlertEvent, NotificationEmailDelivery
from .schema import AlertSummaryItem, AlertTableColumn, AlertTableSection, EmailBatch

ERROR_RETRY_DELAY = timedelta(minutes=15)
STOCK_ALERT_RESEND_COOLDOWN = timedelta(days=7)
MORNING_EMAIL_LOCAL_HOUR = 9
ACTION_TYPES = {
    AlertType.COUNT_ACTION,
    AlertType.RESTOCK_ACTION,
    AlertType.TAKEOUT_ACTION,
    AlertType.TRANSFER_ACTION,
}
RECAP_SECTION_COLOR = AlertSeverity.INFO.color
SEVERITY_RANK = {severity: rank for rank, severity in enumerate(SEVERITY_ORDER)}


class EmailTimingMode(StrEnum):
    """Code-only reason a notification send time was selected."""

    IMMEDIATE = "IMMEDIATE"
    NEXT_HOUR = "NEXT_HOUR"
    DAILY_ALERT = "DAILY_ALERT"
    MORNING_RECAP = "MORNING_RECAP"


@dataclass(frozen=True)
class RecipientAlertSnapshot:
    """Recipient-specific alert inputs after preference and location filtering."""

    stock_states: list[InventoryItemLocationState]
    immediate_events: list[InventoryAlertEvent]
    scheduled_events: list[InventoryAlertEvent]


@dataclass(frozen=True)
class EmailPlan:
    """Code-only plan for one rendered email before it is stored."""

    delivery_key: str
    delivery_kind: NotificationDeliveryKind
    timing_mode: EmailTimingMode
    send_at: datetime
    stock_states: list[InventoryItemLocationState]
    events: list[InventoryAlertEvent]
    report_title: str | None = None


def process_all_alerts(*, force: bool = False, agency_id: int | None = None) -> dict[str, int]:
    """Render pending notification deliveries and send due rows."""
    now = _now()
    stats = {"created": 0, "processed": 0, "sent": 0, "failed": 0, "suppressed": 0}
    with get_session() as session:
        stats["created"] = prepare_notification_deliveries(session, now, force=force, agency_id=agency_id)
        session.flush()
        send_stats = send_due_notification_deliveries(session, now, force=force, agency_id=agency_id)
        stats.update(send_stats)
        session.commit()
    logger.info("Notification email run finished", extra=stats | {"force": force, "agency_id": agency_id})
    return stats


def prepare_notification_deliveries(
    session: Session,
    now: datetime | None = None,
    *,
    force: bool = False,
    agency_id: int | None = None,
) -> int:
    """Create or refresh pending rendered email deliveries from current state/events."""
    now = now or _now()
    created = 0
    queued_event_ids: set[int] = set()
    for agency in _active_agencies(session, agency_id):
        for recipient in list_active_emails(agency.id, session, order_by_id=True):
            created += _prepare_recipient_deliveries(session, agency, recipient, now, queued_event_ids, force=force)

    if queued_event_ids:
        events = session.execute(select(InventoryAlertEvent).where(InventoryAlertEvent.id.in_(queued_event_ids))).scalars()
        for event in events:
            if event.status in {InventoryAlertEventStatus.PENDING, InventoryAlertEventStatus.NO_RECIPIENT}:
                event.status = InventoryAlertEventStatus.QUEUED
                event.queued_at = now
    _mark_pending_events_without_recipients(session, queued_event_ids, agency_id=agency_id)
    logger.debug("Notification deliveries prepared", extra={"created_or_updated": created, "queued_event_count": len(queued_event_ids)})
    return created


def send_due_notification_deliveries(
    session: Session,
    now: datetime | None = None,
    *,
    force: bool = False,
    agency_id: int | None = None,
) -> dict[str, int]:
    """Send due delivery rows once and update delivery status."""
    now = now or _now()
    stats = {"processed": 0, "sent": 0, "failed": 0, "suppressed": 0}
    deliveries = _due_deliveries(session, now, force=force, agency_id=agency_id)
    for delivery in deliveries:
        if quiet_until := _quiet_until_for_delivery(session, delivery, now):
            _postpone_delivery_for_quiet_hours(delivery, quiet_until)
            stats["suppressed"] += 1
            continue
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
    snapshot = _recipient_alert_snapshot(session, agency, recipient, now)
    stock_states = _eligible_stock_states(
        snapshot.stock_states,
        _recent_sent_stock_alert_keys(session, recipient.id, now),
    )
    created = 0
    filtered_snapshot = RecipientAlertSnapshot(
        stock_states=stock_states,
        immediate_events=snapshot.immediate_events,
        scheduled_events=snapshot.scheduled_events,
    )
    for plan in _email_plans_for_recipient(filtered_snapshot, recipient, agency.timezone, now, force=force):
        created += _upsert_delivery_from_plan(
            session,
            agency,
            recipient,
            plan,
            now=now,
        )
        queued_event_ids.update(event.id for event in plan.events)
    return created


def _recipient_alert_snapshot(
    session: Session,
    agency: Agencies,
    recipient: AgencyEmails,
    now: datetime,
) -> RecipientAlertSnapshot:
    stock_states = _stock_states_for_recipient(session, recipient)
    events = _events_for_recipient(session, recipient)
    return RecipientAlertSnapshot(
        stock_states=stock_states,
        immediate_events=[event for event in events if event.alert_type in IMMEDIATE_EVENT_TYPES],
        scheduled_events=[event for event in events if event.alert_type not in IMMEDIATE_EVENT_TYPES],
    )


def _email_plans_for_recipient(
    snapshot: RecipientAlertSnapshot,
    recipient: AgencyEmails,
    timezone: str,
    now: datetime,
    *,
    force: bool,
) -> list[EmailPlan]:
    plans: list[EmailPlan] = []
    due_reports = _due_report_preferences(recipient, timezone, now)
    alert_events = [*snapshot.immediate_events, *snapshot.scheduled_events]
    if snapshot.stock_states or alert_events:
        plans.append(
            _email_plan(
                recipient,
                timezone,
                _alert_timing_mode(recipient.alert_frequency),
                now,
                force=force,
                delivery_kind=NotificationDeliveryKind.ALERT,
                stock_states=snapshot.stock_states,
                events=alert_events,
            )
        )
    if due_reports:
        plans.append(
            _email_plan(
                recipient,
                timezone,
                EmailTimingMode.MORNING_RECAP,
                now,
                force=force,
                delivery_kind=NotificationDeliveryKind.REPORT,
                stock_states=[],
                events=[],
                report_title=_report_title(due_reports),
            )
        )
    return plans


def _email_plan(
    recipient: AgencyEmails,
    timezone: str,
    timing_mode: EmailTimingMode,
    now: datetime,
    *,
    force: bool,
    delivery_kind: NotificationDeliveryKind,
    stock_states: list[InventoryItemLocationState],
    events: list[InventoryAlertEvent],
    report_title: str | None = None,
) -> EmailPlan:
    send_at = _send_at_for_timing(timing_mode, now, timezone, force=force)
    send_at = _send_at_after_quiet_hours(recipient, timezone, send_at)
    return EmailPlan(
        delivery_key=_delivery_key(delivery_kind, timing_mode, send_at),
        delivery_kind=delivery_kind,
        timing_mode=timing_mode,
        send_at=send_at,
        stock_states=stock_states,
        events=events,
        report_title=report_title,
    )


def _upsert_delivery_from_plan(
    session: Session,
    agency: Agencies,
    recipient: AgencyEmails,
    plan: EmailPlan,
    *,
    now: datetime,
) -> int:
    existing = session.scalar(
        select(NotificationEmailDelivery).where(
            NotificationEmailDelivery.agency_id == agency.id,
            NotificationEmailDelivery.agency_email_id == recipient.id,
            NotificationEmailDelivery.delivery_key == plan.delivery_key,
        )
    )
    batch = _build_batch(
        session,
        agency,
        recipient,
        plan,
        now,
    )
    if batch is None or not batch.sections:
        _cancel_open_delivery(existing)
        return 0
    if existing and existing.status == NotificationEmailStatus.SENT:
        return 0

    body_text = render_template("batch_email.txt", batch=batch)
    body_html = render_template("batch_email.html", batch=batch)
    email_delivery = existing or NotificationEmailDelivery(
        agency_id=agency.id,
        agency_email_id=recipient.id,
        recipient_email_snapshot=recipient.email,
        created_at=now,
    )
    email_delivery.status = NotificationEmailStatus.PENDING
    email_delivery.delivery_key = plan.delivery_key
    email_delivery.delivery_kind = plan.delivery_kind
    email_delivery.recipient_email_snapshot = recipient.email
    email_delivery.send_at = plan.send_at
    email_delivery.next_attempt_at = None
    email_delivery.alert_event_ids_json = [event.id for event in plan.events]
    email_delivery.state_alert_keys_json = [key for state in plan.stock_states if (key := _stock_alert_key(state)) is not None]
    email_delivery.subject = batch.subject
    email_delivery.preview_text = _preview_text(batch)
    email_delivery.body_html = body_html
    email_delivery.body_text = body_text
    email_delivery.last_error_type = None
    email_delivery.last_error_message = None
    email_delivery.last_error_at = None
    session.add(email_delivery)
    return 1


def _cancel_open_delivery(delivery: NotificationEmailDelivery | None) -> None:
    if delivery is None or delivery.status not in {NotificationEmailStatus.PENDING, NotificationEmailStatus.ERROR}:
        return
    delivery.status = NotificationEmailStatus.CANCELLED
    delivery.next_attempt_at = None
    delivery.last_error_type = None
    delivery.last_error_message = None
    delivery.last_error_at = None


def _build_batch(
    session: Session,
    agency: Agencies,
    recipient: AgencyEmails,
    plan: EmailPlan,
    now: datetime,
) -> EmailBatch | None:
    alert_sections = _build_sections(session, plan.stock_states, plan.events, agency.timezone)
    recap_sections = _summary_sections(session, agency, recipient, now) if plan.delivery_kind == NotificationDeliveryKind.REPORT else []
    sections = [*alert_sections, *recap_sections]
    if not sections:
        return None
    severity = _severity_style(plan.stock_states, plan.events)
    summary = _summary_items(plan.stock_states, plan.events)
    return EmailBatch(
        agency_email=recipient.email,
        agency_name=agency.display_name,
        generated_at=_display_now(agency.timezone, now),
        subject=_subject(agency.display_name, severity.subject_prefix, plan),
        title=_title(plan),
        intro=_intro(plan.timing_mode, plan.delivery_kind),
        severity_label=severity.value,
        severity_color=severity.color,
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


def _eligible_stock_states(
    states: list[InventoryItemLocationState],
    recent_state_keys: set[str],
) -> list[InventoryItemLocationState]:
    return [state for state in states if (key := _stock_alert_key(state)) is None or key not in recent_state_keys]


def _recent_sent_stock_alert_keys(
    session: Session,
    agency_email_id: int,
    now: datetime,
) -> set[str]:
    cutoff = now - STOCK_ALERT_RESEND_COOLDOWN
    rows = session.execute(
        select(NotificationEmailDelivery.state_alert_keys_json).where(
            NotificationEmailDelivery.agency_email_id == agency_email_id,
            NotificationEmailDelivery.status == NotificationEmailStatus.SENT,
            func.coalesce(NotificationEmailDelivery.sent_at, NotificationEmailDelivery.send_at) >= cutoff,
        )
    ).scalars()
    return {key for keys in rows for key in (keys or []) if isinstance(key, str) and key}


def _stock_alert_key(state: InventoryItemLocationState) -> str | None:
    if state.effective_alert_type is None or state.effective_alert_started_at is None:
        return None
    return (
        f"STATE:{state.agency_id}:{state.item_id}:{state.agency_location_id}:"
        f"{state.effective_alert_type.value}:{state.effective_alert_started_at.isoformat()}"
    )


def _events_for_recipient(session: Session, recipient: AgencyEmails) -> list[InventoryAlertEvent]:
    rows = session.execute(
        select(InventoryAlertEvent)
        .where(
            InventoryAlertEvent.agency_id == recipient.agency_id,
            InventoryAlertEvent.status.in_(
                [
                    InventoryAlertEventStatus.PENDING,
                    InventoryAlertEventStatus.NO_RECIPIENT,
                    InventoryAlertEventStatus.QUEUED,
                ]
            ),
            InventoryAlertEvent.alert_type.in_(DISCRETE_EVENT_TYPES),
        )
        .order_by(InventoryAlertEvent.event_at, InventoryAlertEvent.id)
    ).scalars()
    return [event for event in rows if _recipient_allows_event(session, recipient, event)]


def _mark_pending_events_without_recipients(
    session: Session,
    queued_event_ids: set[int],
    *,
    agency_id: int | None,
) -> None:
    stmt = select(InventoryAlertEvent).where(
        InventoryAlertEvent.status == InventoryAlertEventStatus.PENDING,
        InventoryAlertEvent.alert_type.in_(DISCRETE_EVENT_TYPES),
    )
    if agency_id is not None:
        stmt = stmt.where(InventoryAlertEvent.agency_id == agency_id)
    for event in session.execute(stmt).scalars():
        if event.id not in queued_event_ids:
            event.status = InventoryAlertEventStatus.NO_RECIPIENT


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
    rows = [
        _stock_row(state, item_names, location_names, timezone)
        for state in sorted(
            (state for state in states if state.effective_alert_type == alert_type),
            key=lambda state: _stock_section_sort_key(state, item_names, alert_type),
        )
    ]
    if not rows:
        return None
    return AlertTableSection(
        title=title,
        note=note,
        color=alert_type.color,
        columns=columns,
        rows=rows,
    )


def _stock_row(
    state: InventoryItemLocationState,
    item_names: dict[int, str],
    location_names: dict[int, str],
    timezone: str,
) -> dict[str, str | int | float | None]:
    return {
        "item_name": item_names.get(state.item_id, str(state.item_id)),
        "locations": location_names.get(state.agency_location_id, str(state.agency_location_id)),
        "current_total": _format_total_quantity(state.total_quantity),
        "min_quantity": state.min_quantity_snapshot,
        "lead_time_days": _format_day_count(state.lead_time_days_snapshot),
        "prediction": _state_prediction(state),
        "confidence": _format_confidence_percent(state.confidence_percent),
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
            "days_since_last_count": event.payload_json.get("days_since_last_count", "Never"),
            "current_total": _format_total_quantity(event.payload_json.get("current_total")),
        }
        for event in sorted(
            (event for event in events if event.alert_type == AlertType.STALE_COUNT),
            key=lambda event: -int(event.payload_json.get("days_since_last_count") or 0),
        )
    ]
    return _simple_section(
        "Stale Counts",
        "Count these item/location pairs before the next incoming delivery or vendor restock.",
        AlertType.STALE_COUNT.color,
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
            "current_total": _format_total_quantity(event.payload_json.get("current_total")),
        }
        for event in sorted(
            (event for event in events if event.alert_type == AlertType.RARE_TAKEOUT),
            key=lambda event: -int(event.payload_json.get("days_since_last_takeout") or 0),
        )
    ]
    return _simple_section(
        "Rare Takeouts",
        "Takeout activity is unusual for this item/location.",
        AlertType.RARE_TAKEOUT.color,
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
            "scan_type": _format_scan_type(event.payload_json),
            "quantity": event.payload_json.get("quantity"),
            "admin_action": "Yes" if event.payload_json.get("admin_action") else "No",
            "time_scanned": _display_datetime(event.payload_json.get("time_scanned"), timezone),
        }
        for event in sorted(
            (event for event in events if event.alert_type in ACTION_TYPES),
            key=lambda event: _sort_datetime_value(event.payload_json.get("time_scanned")) or datetime.min,
            reverse=True,
        )
    ]
    return _simple_section(
        "Scan Activity",
        "Configured count, restock, takeout, and transfer notifications.",
        AlertSeverity.INFO.color,
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
        for event in sorted(
            (event for event in events if event.alert_type == AlertType.UNKNOWN_UPC),
            key=lambda event: _sort_datetime_value(event.payload_json.get("created_at")) or datetime.min,
        )
    ]
    return _simple_section(
        "Unknown UPCs",
        "These UPCs need admin review before they can scan to an item.",
        AlertType.UNKNOWN_UPC.color,
        rows,
        ["upc:UPC", "lookup_title:Lookup Name", "created_at:First Seen"],
    )


def _simple_section(
    title: str,
    note: str,
    color: str,
    rows: list[dict[str, Any]],
    column_specs: list[str],
) -> AlertTableSection | None:
    if not rows:
        return None
    columns = [AlertTableColumn(key=spec.split(":", 1)[0], label=spec.split(":", 1)[1]) for spec in column_specs]
    return AlertTableSection(title=title, note=note, color=color, columns=columns, rows=rows)


def _summary_sections(
    session: Session,
    agency: Agencies,
    recipient: AgencyEmails,
    now: datetime,
) -> list[AlertTableSection]:
    local_now = _local_now(agency.timezone, now)
    return [
        section
        for preference in due_summary_preferences(local_now)
        if bool(getattr(recipient, preference.field))
        and preference.bounds is not None
        and (section := _summary_section(session, agency.id, preference.label, preference.bounds(local_now)))
    ]


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
        RECAP_SECTION_COLOR,
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


def _stock_section_sort_key(
    state: InventoryItemLocationState,
    item_names: dict[int, str],
    alert_type: AlertType,
) -> tuple[Any, ...]:
    item_name = item_names.get(state.item_id, str(state.item_id)).lower()
    if alert_type == AlertType.STOCKOUT:
        return (item_name, state.agency_location_id)
    if alert_type == AlertType.STOCKOUT_FORECAST:
        return (state.days_until_stockout is None, state.days_until_stockout or 0.0, item_name, state.agency_location_id)
    if alert_type == AlertType.LOW_STOCK:
        return (state.total_quantity, item_name, state.agency_location_id)
    return (state.days_until_low is None, state.days_until_low or 0.0, item_name, state.agency_location_id)


def _sort_datetime_value(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _due_deliveries(
    session: Session,
    now: datetime,
    *,
    force: bool,
    agency_id: int | None,
) -> list[NotificationEmailDelivery]:
    filters = []
    if agency_id is not None:
        filters.append(NotificationEmailDelivery.agency_id == agency_id)
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
            if event.status in {
                InventoryAlertEventStatus.PENDING,
                InventoryAlertEventStatus.NO_RECIPIENT,
                InventoryAlertEventStatus.QUEUED,
            }:
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


def _quiet_until_for_delivery(session: Session, delivery: NotificationEmailDelivery, now: datetime) -> datetime | None:
    recipient = session.get(AgencyEmails, delivery.agency_email_id)
    agency = session.get(Agencies, delivery.agency_id)
    if recipient is None or agency is None:
        return None
    return _quiet_end_utc(recipient, agency.timezone, now)


def _postpone_delivery_for_quiet_hours(
    delivery: NotificationEmailDelivery,
    quiet_until: datetime,
) -> None:
    postponed_send_at = max(delivery.send_at, quiet_until)
    if postponed_send_at != delivery.send_at:
        logger.info(
            "Notification delivery postponed for quiet hours",
            extra={
                "notification_email_delivery_id": delivery.id,
                "agency_id": delivery.agency_id,
                "agency_email_id": delivery.agency_email_id,
                "original_send_at": delivery.send_at.isoformat(),
                "postponed_send_at": postponed_send_at.isoformat(),
            },
        )
    delivery.send_at = postponed_send_at
    delivery.next_attempt_at = None


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
        f"Send At: {delivery.send_at}\n"
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


def _active_agencies(session: Session, agency_id: int | None = None) -> list[Agencies]:
    stmt = select(Agencies).where(Agencies.active.is_(True)).order_by(Agencies.id)
    if agency_id is not None:
        stmt = stmt.where(Agencies.id == agency_id)
    return list(session.execute(stmt).scalars().all())


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


def _summary_items(stock_states: list[InventoryItemLocationState], events: list[InventoryAlertEvent]) -> list[AlertSummaryItem]:
    counts = Counter([state.effective_alert_type for state in stock_states if state.effective_alert_type] + [event.alert_type for event in events])
    return [
        AlertSummaryItem(label=LABEL_BY_TYPE[alert_type], count=count, color=alert_type.color) for alert_type, count in counts.items() if count > 0
    ]


def _severity_style(stock_states: list[InventoryItemLocationState], events: list[InventoryAlertEvent]) -> AlertSeverity:
    severity = AlertSeverity.INFO
    if any(state.effective_alert_type == AlertType.STOCKOUT for state in stock_states):
        severity = AlertSeverity.CRITICAL
    for state in stock_states:
        severity = _higher_severity(severity, state.effective_severity)
    for event in events:
        severity = _higher_severity(severity, event.severity)
    return severity


def _subject(agency_name: str, severity_prefix: str, plan: EmailPlan) -> str:
    if plan.delivery_kind == NotificationDeliveryKind.REPORT:
        return report_subject(plan.report_title or INVENTORY_SUMMARIES_TITLE, agency_name)
    return f"{severity_prefix} Inventory Alerts - {agency_name}"


def _title(plan: EmailPlan) -> str:
    if plan.delivery_kind == NotificationDeliveryKind.REPORT:
        return plan.report_title or INVENTORY_SUMMARIES_TITLE
    return "Inventory Alerts"


def _due_report_preferences(recipient: AgencyEmails, timezone: str, now: datetime) -> tuple[NotificationPreference, ...]:
    local_now = _local_now(timezone, now)
    if local_now.hour != MORNING_EMAIL_LOCAL_HOUR:
        return ()
    return tuple(preference for preference in due_summary_preferences(local_now) if bool(getattr(recipient, preference.field)))


def _report_title(preferences: tuple[NotificationPreference, ...]) -> str:
    if preferences:
        return inventory_summary_title(preferences[-1].label)
    return INVENTORY_SUMMARIES_TITLE


def _intro(timing_mode: EmailTimingMode, delivery_kind: NotificationDeliveryKind) -> str:
    if delivery_kind == NotificationDeliveryKind.REPORT:
        return "This email includes your periodic inventory recap."
    if timing_mode == EmailTimingMode.IMMEDIATE:
        return "This email includes alert activity configured for immediate notification."
    return "This email includes grouped inventory alerts scheduled for review."


def _higher_severity(left: AlertSeverity, right: AlertSeverity | None) -> AlertSeverity:
    if right is None:
        return left
    return right if SEVERITY_RANK[right] < SEVERITY_RANK[left] else left


def _preview_text(batch: EmailBatch) -> str:
    if not batch.summary:
        return "Inventory IQ notification update."
    parts = [f"{item.count} {item.label}" for item in batch.summary[:3]]
    return ", ".join(parts)[:255]


def _round_up_hour(value: datetime) -> datetime:
    rounded = value.replace(minute=0, second=0, microsecond=0)
    if rounded < value:
        rounded += timedelta(hours=1)
    return rounded


def _alert_timing_mode(frequency: AlertEmailFrequency) -> EmailTimingMode:
    if frequency == AlertEmailFrequency.INSTANT:
        return EmailTimingMode.IMMEDIATE
    if frequency == AlertEmailFrequency.DAILY:
        return EmailTimingMode.DAILY_ALERT
    return EmailTimingMode.NEXT_HOUR


def _send_at_for_timing(timing_mode: EmailTimingMode, now: datetime, timezone: str, *, force: bool) -> datetime:
    if force or timing_mode == EmailTimingMode.IMMEDIATE:
        return now
    if timing_mode == EmailTimingMode.MORNING_RECAP:
        return _report_window_start(timezone, now)
    if timing_mode == EmailTimingMode.DAILY_ALERT:
        return _daily_alert_send_at(timezone, now)
    return _round_up_hour(now)


def _daily_alert_send_at(timezone: str, now: datetime) -> datetime:
    local = _local_now(timezone, now)
    if local.hour == MORNING_EMAIL_LOCAL_HOUR:
        return _alert_window_start(timezone, now)
    return _next_alert_window_start(timezone, now)


def _alert_window_start(timezone: str, now: datetime) -> datetime:
    local = _local_now(timezone, now)
    return _utc_naive(local.replace(hour=MORNING_EMAIL_LOCAL_HOUR, minute=0, second=0, microsecond=0))


def _next_alert_window_start(timezone: str, now: datetime) -> datetime:
    local = _local_now(timezone, now)
    target = local.replace(hour=MORNING_EMAIL_LOCAL_HOUR, minute=0, second=0, microsecond=0)
    if local.hour > MORNING_EMAIL_LOCAL_HOUR:
        target += timedelta(days=1)
    return _utc_naive(target)


def _report_window_start(timezone: str, now: datetime) -> datetime:
    local = _local_now(timezone, now)
    return _utc_naive(local.replace(hour=MORNING_EMAIL_LOCAL_HOUR, minute=0, second=0, microsecond=0))


def _send_at_after_quiet_hours(recipient: AgencyEmails, timezone: str, send_at: datetime) -> datetime:
    return _quiet_end_utc(recipient, timezone, send_at) or send_at


def _delivery_key(
    delivery_kind: NotificationDeliveryKind,
    timing_mode: EmailTimingMode,
    send_at: datetime,
) -> str:
    return f"{delivery_kind.value}:{timing_mode.value}:{send_at.isoformat()}"


def _quiet_end_utc(recipient: AgencyEmails, timezone: str, instant_utc: datetime) -> datetime | None:
    try:
        quiet_start = _parse_quiet_time(recipient.quiet_start_time)
        quiet_end = _parse_quiet_time(recipient.quiet_end_time)
    except ValueError as exc:
        logger.warning(
            "Notification quiet hours ignored because stored values are invalid",
            extra={"agency_id": recipient.agency_id, "agency_email_id": recipient.id, "error": str(exc)},
        )
        return None
    if quiet_start is None or quiet_end is None or quiet_start == quiet_end:
        return None

    local_now = _local_now(timezone, instant_utc)
    if not _time_is_quiet(local_now.time(), quiet_start, quiet_end):
        return None
    return _utc_naive(_local_quiet_end(local_now, quiet_start, quiet_end))


def _parse_quiet_time(value: str | None) -> time | None:
    if not value:
        return None
    hour, minute = (int(part) for part in value.split(":", maxsplit=1))
    return time(hour=hour, minute=minute)


def _time_is_quiet(local_time: time, quiet_start: time, quiet_end: time) -> bool:
    if quiet_start < quiet_end:
        return quiet_start <= local_time < quiet_end
    return local_time >= quiet_start or local_time < quiet_end


def _local_quiet_end(local_now: datetime, quiet_start: time, quiet_end: time) -> datetime:
    quiet_end_today = local_now.replace(hour=quiet_end.hour, minute=quiet_end.minute, second=0, microsecond=0)
    if quiet_start < quiet_end or local_now.time() < quiet_end:
        return quiet_end_today
    return quiet_end_today + timedelta(days=1)


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


def _format_total_quantity(value: Any) -> str:
    return f"{value} total"


def _format_day_count(value: Any) -> str:
    return "" if value is None else f"{value} days"


def _state_prediction(state: InventoryItemLocationState) -> str | None:
    if state.effective_alert_type == AlertType.STOCKOUT_FORECAST and state.days_until_stockout is not None:
        return f"{state.days_until_stockout} days until stockout"
    if state.effective_alert_type == AlertType.LOW_STOCK_FORECAST and state.days_until_low is not None:
        return f"{state.days_until_low} days until low"
    return None


def _format_confidence_percent(value: Any) -> str:
    rounded = rounded_confidence_percent(value)
    return "" if rounded is None else f"{rounded}%"


def _format_scan_type(payload: dict[str, Any]) -> str:
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


def _local_now(timezone: str, now: datetime) -> datetime:
    aware = now.replace(tzinfo=UTC) if now.tzinfo is None else now
    return aware.astimezone(ZoneInfo(timezone or "UTC"))


def _utc_naive(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(tzinfo=None)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None
