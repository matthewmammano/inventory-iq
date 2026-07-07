"""Render and send state-driven inventory notification emails."""

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from enum import StrEnum
from typing import Any
from zoneinfo import ZoneInfo

from flask import render_template
from loguru import logger
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.auth.location_filters import alert_matches_location_filter, validate_location_filter_ids
from app.auth.models import Agency, NotificationRecipient
from app.auth.notification_preferences import AlertEmailFrequency, NotificationPreference, due_summary_preferences
from app.auth.queries import list_active_emails
from app.inventory.constants import UnknownUpcStatus
from app.inventory.models import InventoryItemLocationState, UnknownUpcScan
from app.shared.clock import utc_now_naive
from app.shared.database import get_session
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
from .developer_alerts import send_developer_delivery_failure_alert
from .email_delivery import deliver_notification_email
from .email_sections import build_alert_sections, build_summary_sections
from .models import InventoryAlertEvent, NotificationEmailDelivery
from .schema import AlertSummaryItem, EmailBatch

ERROR_RETRY_DELAY = timedelta(minutes=15)
STOCK_ALERT_RESEND_COOLDOWN = timedelta(days=7)
MORNING_EMAIL_LOCAL_HOUR = 9
SEVERITY_RANK = {severity: rank for rank, severity in enumerate(SEVERITY_ORDER)}
OPEN_DELIVERY_STATUSES = (NotificationEmailStatus.PENDING, NotificationEmailStatus.ERROR)
QUEUEABLE_EVENT_STATUSES = (InventoryAlertEventStatus.PENDING, InventoryAlertEventStatus.NO_RECIPIENT)
NOTIFIABLE_EVENT_STATUSES = (
    InventoryAlertEventStatus.PENDING,
    InventoryAlertEventStatus.NO_RECIPIENT,
    InventoryAlertEventStatus.QUEUED,
)


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
            if event.status in QUEUEABLE_EVENT_STATUSES:
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
    agency: Agency,
    recipient: NotificationRecipient,
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
    agency: Agency,
    recipient: NotificationRecipient,
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
    recipient: NotificationRecipient,
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
    recipient: NotificationRecipient,
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
    agency: Agency,
    recipient: NotificationRecipient,
    plan: EmailPlan,
    *,
    now: datetime,
) -> int:
    existing = session.scalar(
        select(NotificationEmailDelivery).where(
            NotificationEmailDelivery.agency_id == agency.id,
            NotificationEmailDelivery.notification_recipient_id == recipient.id,
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
        notification_recipient_id=recipient.id,
        recipient_email_snapshot=recipient.email,
        created_at=now,
    )
    email_delivery.status = NotificationEmailStatus.PENDING
    email_delivery.delivery_key = plan.delivery_key
    email_delivery.delivery_kind = plan.delivery_kind
    email_delivery.recipient_email_snapshot = recipient.email
    email_delivery.send_at = plan.send_at
    email_delivery.alert_event_ids_json = [event.id for event in plan.events]
    email_delivery.state_alert_keys_json = [key for state in plan.stock_states if (key := _stock_alert_key(state)) is not None]
    email_delivery.subject = batch.subject
    email_delivery.preview_text = _preview_text(batch)
    email_delivery.body_html = body_html
    email_delivery.body_text = body_text
    _clear_delivery_error_state(email_delivery)
    session.add(email_delivery)
    return 1


def _cancel_open_delivery(delivery: NotificationEmailDelivery | None) -> None:
    if delivery is None or delivery.status not in OPEN_DELIVERY_STATUSES:
        return
    delivery.status = NotificationEmailStatus.CANCELLED
    _clear_delivery_error_state(delivery)


def _build_batch(
    session: Session,
    agency: Agency,
    recipient: NotificationRecipient,
    plan: EmailPlan,
    now: datetime,
) -> EmailBatch | None:
    alert_sections = build_alert_sections(session, plan.stock_states, plan.events, agency.timezone)
    recap_sections = build_summary_sections(session, agency, recipient, now) if plan.delivery_kind == NotificationDeliveryKind.REPORT else []
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


def _stock_states_for_recipient(session: Session, recipient: NotificationRecipient) -> list[InventoryItemLocationState]:
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
    notification_recipient_id: int,
    now: datetime,
) -> set[str]:
    cutoff = now - STOCK_ALERT_RESEND_COOLDOWN
    rows = session.execute(
        select(NotificationEmailDelivery.state_alert_keys_json).where(
            NotificationEmailDelivery.notification_recipient_id == notification_recipient_id,
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


def _events_for_recipient(session: Session, recipient: NotificationRecipient) -> list[InventoryAlertEvent]:
    rows = session.execute(
        select(InventoryAlertEvent)
        .where(
            InventoryAlertEvent.agency_id == recipient.agency_id,
            InventoryAlertEvent.status.in_(NOTIFIABLE_EVENT_STATUSES),
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
    recipient: NotificationRecipient,
    state: InventoryItemLocationState,
) -> bool:
    alert_type = state.effective_alert_type
    if alert_type is None or not recipient.preference_enabled(PREFERENCE_BY_TYPE[alert_type]):
        return False
    return _recipient_allows_location(session, recipient, {"agency_location_id": state.agency_location_id})


def _recipient_allows_event(
    session: Session,
    recipient: NotificationRecipient,
    event: InventoryAlertEvent,
) -> bool:
    if event.alert_type == AlertType.UNKNOWN_UPC and not _unknown_upc_is_pending(session, event):
        return False
    preference = PREFERENCE_BY_TYPE.get(event.alert_type)
    if preference and not recipient.preference_enabled(preference):
        return False
    return _recipient_allows_location(session, recipient, event.payload_json)


def _recipient_allows_location(session: Session, recipient: NotificationRecipient, payload: dict[str, Any]) -> bool:
    try:
        location_ids = validate_location_filter_ids(session, recipient.agency_id, recipient.location_filter_ids)
    except ValueError as exc:
        logger.warning(
            "Notification recipient skipped because of an invalid location filter",
            extra={"agency_id": recipient.agency_id, "notification_recipient_id": recipient.id, "error": str(exc)},
        )
        return False
    return alert_matches_location_filter(location_ids, payload)


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
        filters.append(NotificationEmailDelivery.status.in_(OPEN_DELIVERY_STATUSES))
    return list(
        session.execute(select(NotificationEmailDelivery).where(*filters).order_by(NotificationEmailDelivery.send_at, NotificationEmailDelivery.id))
        .scalars()
        .all()
    )


def _mark_delivery_sent(session: Session, delivery: NotificationEmailDelivery, now: datetime) -> None:
    delivery.status = NotificationEmailStatus.SENT
    delivery.sent_at = now
    _clear_delivery_error_state(delivery)
    if delivery.alert_event_ids_json:
        events = session.execute(select(InventoryAlertEvent).where(InventoryAlertEvent.id.in_(delivery.alert_event_ids_json))).scalars()
        for event in events:
            if event.status in NOTIFIABLE_EVENT_STATUSES:
                event.status = InventoryAlertEventStatus.NOTIFIED
                event.notified_at = now


def _mark_delivery_failed(delivery: NotificationEmailDelivery, now: datetime) -> None:
    delivery.status = NotificationEmailStatus.ERROR
    delivery.attempt_count = int(delivery.attempt_count or 0) + 1
    delivery.last_error_type = "EMAIL_DELIVERY_FAILED"
    delivery.last_error_message = "Email provider did not accept the notification delivery."
    delivery.last_error_at = now
    delivery.next_attempt_at = max(delivery.send_at, now + ERROR_RETRY_DELAY)
    send_developer_delivery_failure_alert(delivery)


def _quiet_until_for_delivery(session: Session, delivery: NotificationEmailDelivery, now: datetime) -> datetime | None:
    recipient = session.get(NotificationRecipient, delivery.notification_recipient_id)
    agency = session.get(Agency, delivery.agency_id)
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
                "notification_recipient_id": delivery.notification_recipient_id,
                "original_send_at": delivery.send_at.isoformat(),
                "postponed_send_at": postponed_send_at.isoformat(),
            },
        )
    delivery.send_at = postponed_send_at
    delivery.next_attempt_at = None


def _clear_delivery_error_state(delivery: NotificationEmailDelivery) -> None:
    delivery.next_attempt_at = None
    delivery.last_error_type = None
    delivery.last_error_message = None
    delivery.last_error_at = None


def _active_agencies(session: Session, agency_id: int | None = None) -> list[Agency]:
    stmt = select(Agency).where(Agency.active.is_(True)).order_by(Agency.id)
    if agency_id is not None:
        stmt = stmt.where(Agency.id == agency_id)
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


def _due_report_preferences(recipient: NotificationRecipient, timezone: str, now: datetime) -> tuple[NotificationPreference, ...]:
    local_now = _local_now(timezone, now)
    if local_now.hour != MORNING_EMAIL_LOCAL_HOUR:
        return ()
    return tuple(preference for preference in due_summary_preferences(local_now) if recipient.preference_enabled(preference.key))


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


def _send_at_after_quiet_hours(recipient: NotificationRecipient, timezone: str, send_at: datetime) -> datetime:
    return _quiet_end_utc(recipient, timezone, send_at) or send_at


def _delivery_key(
    delivery_kind: NotificationDeliveryKind,
    timing_mode: EmailTimingMode,
    send_at: datetime,
) -> str:
    return f"{delivery_kind.value}:{timing_mode.value}:{send_at.isoformat()}"


def _quiet_end_utc(recipient: NotificationRecipient, timezone: str, instant_utc: datetime) -> datetime | None:
    try:
        quiet_start = _parse_quiet_time(recipient.quiet_start_time)
        quiet_end = _parse_quiet_time(recipient.quiet_end_time)
    except ValueError as exc:
        logger.warning(
            "Notification quiet hours ignored because stored values are invalid",
            extra={"agency_id": recipient.agency_id, "notification_recipient_id": recipient.id, "error": str(exc)},
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


def _format_local_datetime(value: datetime) -> str:
    return value.strftime("%B %d, %Y %H:%M")


def _now() -> datetime:
    return utc_now_naive()


def _local_now(timezone: str, now: datetime) -> datetime:
    aware = now.replace(tzinfo=UTC) if now.tzinfo is None else now
    return aware.astimezone(ZoneInfo(timezone or "UTC"))


def _utc_naive(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(tzinfo=None)
