"""Decide and send inventory notification emails, once per run.

Each run asks, per recipient: which open alerts are they allowed to see, which
are due given their notification history, and is it the right time for their
cadence? A recipient is due for an alert when they have never been notified about
it, or when its type allows resending and the cooldown has elapsed. Escalation
and recurrence need no special case -- they produce a brand-new alert row, which
has no notification history and is therefore due at once. Content is rendered
fresh at send time; only a lightweight audit row and ledger entries are stored.
"""

from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.location_filters import alert_matches_location_filter, validate_location_filter_ids
from app.auth.models import Agency, NotificationRecipient
from app.auth.notification_preferences import AlertEmailFrequency, NotificationPreference, due_summary_preferences
from app.auth.queries import list_active_emails
from app.inventory.models import InventoryItemLocationState
from app.shared.clock import utc_now_naive
from app.shared.database import get_session
from app.shared.email_subjects import INVENTORY_SUMMARIES_TITLE, inventory_summary_title, report_subject

from .constants import (
    LABEL_BY_TYPE,
    PREFERENCE_BY_TYPE,
    RESEND_AFTER_BY_TYPE,
    SEVERITY_ORDER,
    STOCK_ALERT_TYPES,
    AlertSeverity,
    AlertStatus,
    DeliveryStatus,
    NotificationDeliveryKind,
)
from .developer_alerts import send_developer_delivery_failure_alert
from .email_delivery import deliver_batch
from .email_sections import build_alert_sections, build_summary_sections
from .models import Alert, AlertNotification, EmailDelivery
from .schema import AlertSummaryItem, EmailBatch

MORNING_EMAIL_LOCAL_HOUR = 9
HOURLY_ALERT_INTERVAL = timedelta(hours=1)
NOTIFICATION_RETRY_DELAYS_SECONDS: tuple[int, ...] = ()  # fail fast; the 10-minute cron is the retry
SEVERITY_RANK = {severity: rank for rank, severity in enumerate(SEVERITY_ORDER)}
STAT_KEYS = ("alerts_sent", "reports_sent", "failed", "suppressed")


@dataclass(frozen=True)
class AlertEmail:
    """A composed notification email and the alerts it credits as notified."""

    batch: EmailBatch
    notified_alerts: tuple[Alert, ...] = field(default_factory=tuple)


def process_all_alerts(*, force: bool = False, agency_id: int | None = None) -> dict[str, int]:
    """Send every due alert and report email, one pass over active recipients."""
    now = _now()
    outcomes: Counter[str] = Counter()
    with get_session() as session:
        for agency in _active_agencies(session, agency_id):
            for recipient in list_active_emails(agency.id, session, order_by_id=True):
                outcomes.update(_process_recipient(session, agency, recipient, now, force=force))
        session.commit()
    stats = {key: outcomes.get(key, 0) for key in STAT_KEYS}
    logger.info("Notification email run finished", extra=stats | {"force": force, "agency_id": agency_id})
    return stats


def _process_recipient(session: Session, agency: Agency, recipient: NotificationRecipient, now: datetime, *, force: bool) -> list[str]:
    if not force and _in_quiet_hours(recipient, agency.timezone, now):
        return ["suppressed"]
    return _process_alerts(session, agency, recipient, now, force=force) + _process_report(session, agency, recipient, now, force=force)


def _process_alerts(session: Session, agency: Agency, recipient: NotificationRecipient, now: datetime, *, force: bool) -> list[str]:
    if not force and not _alert_cadence_ready(session, recipient, agency.timezone, now):
        return []
    due_alerts = _due_alerts(session, agency.id, recipient, now)
    if not due_alerts:
        return []
    email = _build_alert_email(session, agency, recipient, due_alerts, now)
    if email is None:
        return []
    if deliver_batch(email.batch, retry_delays_seconds=NOTIFICATION_RETRY_DELAYS_SECONDS):
        _record_alert_sent(session, agency, recipient, email, now)
        return ["alerts_sent"]
    _record_failure(session, agency, recipient, NotificationDeliveryKind.ALERT, email.batch, now)
    return ["failed"]


def _process_report(session: Session, agency: Agency, recipient: NotificationRecipient, now: datetime, *, force: bool) -> list[str]:
    if not force and _already_reported_today(session, recipient, agency.timezone, now):
        return []
    email = _build_report_email(session, agency, recipient, now, force=force)
    if email is None:
        return []
    if deliver_batch(email.batch, retry_delays_seconds=NOTIFICATION_RETRY_DELAYS_SECONDS):
        _record_report_sent(session, agency, recipient, email, now)
        return ["reports_sent"]
    _record_failure(session, agency, recipient, NotificationDeliveryKind.REPORT, email.batch, now)
    return ["failed"]


# --------------------------------------------------------------------------- #
# Eligibility
# --------------------------------------------------------------------------- #


def _due_alerts(session: Session, agency_id: int, recipient: NotificationRecipient, now: datetime) -> list[Alert]:
    allowed = [alert for alert in _open_alerts(session, agency_id) if _recipient_allows_alert(session, recipient, alert)]
    if not allowed:
        return []
    last_notified = _last_notified_by_alert(session, recipient.id, [alert.id for alert in allowed])
    return [alert for alert in allowed if _alert_due(alert, last_notified.get(alert.id), now)]


def _alert_due(alert: Alert, last_notified_at: datetime | None, now: datetime) -> bool:
    if last_notified_at is None:
        return True
    cooldown = RESEND_AFTER_BY_TYPE.get(alert.alert_type)
    if cooldown is None:
        return False
    return now - last_notified_at >= cooldown


def _open_alerts(session: Session, agency_id: int) -> list[Alert]:
    return list(
        session.execute(select(Alert).where(Alert.agency_id == agency_id, Alert.status == AlertStatus.OPEN).order_by(Alert.opened_at, Alert.id))
        .scalars()
        .all()
    )


def _last_notified_by_alert(session: Session, recipient_id: int, alert_ids: list[int]) -> dict[int, datetime]:
    if not alert_ids:
        return {}
    rows = (
        session.execute(
            select(AlertNotification.alert_id, func.max(AlertNotification.notified_at))
            .where(AlertNotification.notification_recipient_id == recipient_id, AlertNotification.alert_id.in_(alert_ids))
            .group_by(AlertNotification.alert_id)
        )
        .tuples()
        .all()
    )
    return dict(rows)


def _recipient_allows_alert(session: Session, recipient: NotificationRecipient, alert: Alert) -> bool:
    preference = PREFERENCE_BY_TYPE.get(alert.alert_type)
    if preference and not recipient.preference_enabled(preference):
        return False
    try:
        location_ids = validate_location_filter_ids(session, recipient.agency_id, recipient.location_filter_ids)
    except ValueError as exc:
        logger.warning(
            "Notification recipient skipped because of an invalid location filter",
            extra={"agency_id": recipient.agency_id, "notification_recipient_id": recipient.id, "error": str(exc)},
        )
        return False
    return alert_matches_location_filter(location_ids, _location_details(alert))


def _location_details(alert: Alert) -> dict[str, object]:
    # Discrete alerts carry location keys in `detail`; stock alerts keep detail
    # empty and render live, so their location comes from the column.
    return alert.detail or {"agency_location_id": alert.agency_location_id}


# --------------------------------------------------------------------------- #
# Composition
# --------------------------------------------------------------------------- #


def _build_alert_email(
    session: Session, agency: Agency, recipient: NotificationRecipient, due_alerts: list[Alert], now: datetime
) -> AlertEmail | None:
    stock_pairs = _stock_pairs(session, agency.id, [alert for alert in due_alerts if alert.alert_type in STOCK_ALERT_TYPES])
    discrete_alerts = [alert for alert in due_alerts if alert.alert_type not in STOCK_ALERT_TYPES]
    sections = build_alert_sections(session, [(alert.alert_type, state) for alert, state in stock_pairs], discrete_alerts, agency.timezone)
    if not sections:
        return None

    notified_alerts = tuple([alert for alert, _ in stock_pairs] + discrete_alerts)
    severity = _email_severity(notified_alerts)
    batch = EmailBatch(
        agency_email=recipient.email,
        agency_name=agency.display_name,
        generated_at=_display_now(agency.timezone, now),
        subject=f"{severity.subject_prefix} Inventory Alerts - {agency.display_name}",
        title="Inventory Alerts",
        intro=_alert_intro(recipient.alert_frequency),
        severity_label=severity.value,
        severity_color=severity.color,
        summary=_summary_items(notified_alerts),
        sections=sections,
    )
    return AlertEmail(batch=batch, notified_alerts=notified_alerts)


def _build_report_email(session: Session, agency: Agency, recipient: NotificationRecipient, now: datetime, *, force: bool) -> AlertEmail | None:
    due_reports = _due_report_preferences(recipient, agency.timezone, now, force=force)
    if not due_reports:
        return None
    sections = build_summary_sections(session, agency, recipient, now)
    if not sections:
        return None

    report_title = _report_title(due_reports)
    batch = EmailBatch(
        agency_email=recipient.email,
        agency_name=agency.display_name,
        generated_at=_display_now(agency.timezone, now),
        subject=report_subject(report_title, agency.display_name),
        title=report_title,
        intro="This email includes your periodic inventory recap.",
        severity_label=AlertSeverity.INFO.value,
        severity_color=AlertSeverity.INFO.color,
        summary=[],
        sections=sections,
    )
    return AlertEmail(batch=batch)


def _stock_pairs(session: Session, agency_id: int, stock_alerts: list[Alert]) -> list[tuple[Alert, InventoryItemLocationState]]:
    keys = {(alert.item_id, alert.agency_location_id) for alert in stock_alerts if alert.item_id and alert.agency_location_id}
    if not keys:
        return []
    states = session.execute(
        select(InventoryItemLocationState).where(
            InventoryItemLocationState.agency_id == agency_id,
            InventoryItemLocationState.item_id.in_({item_id for item_id, _ in keys}),
            InventoryItemLocationState.agency_location_id.in_({location_id for _, location_id in keys}),
        )
    ).scalars()
    state_by_key = {(state.item_id, state.agency_location_id): state for state in states}
    pairs = []
    for alert in stock_alerts:
        if alert.item_id is None or alert.agency_location_id is None:
            continue
        state = state_by_key.get((alert.item_id, alert.agency_location_id))
        if state is not None:
            pairs.append((alert, state))
    return pairs


def _email_severity(alerts: tuple[Alert, ...]) -> AlertSeverity:
    severity = AlertSeverity.INFO
    for alert in alerts:
        severity = _higher_severity(severity, alert.alert_type.severity)
    return severity


def _higher_severity(left: AlertSeverity, right: AlertSeverity) -> AlertSeverity:
    return right if SEVERITY_RANK[right] < SEVERITY_RANK[left] else left


def _summary_items(alerts: tuple[Alert, ...]) -> list[AlertSummaryItem]:
    counts = Counter(alert.alert_type for alert in alerts)
    return [
        AlertSummaryItem(label=LABEL_BY_TYPE[alert_type], count=count, color=alert_type.color) for alert_type, count in counts.items() if count > 0
    ]


def _alert_intro(frequency: AlertEmailFrequency) -> str:
    if frequency == AlertEmailFrequency.INSTANT:
        return "This email includes alert activity configured for immediate notification."
    return "This email includes grouped inventory alerts scheduled for review."


def _preview_text(batch: EmailBatch) -> str:
    if not batch.summary:
        return "Inventory IQ notification update."
    return ", ".join(f"{item.count} {item.label}" for item in batch.summary[:3])[:255]


# --------------------------------------------------------------------------- #
# Persistence (write-once audit + ledger)
# --------------------------------------------------------------------------- #


def _record_alert_sent(session: Session, agency: Agency, recipient: NotificationRecipient, email: AlertEmail, now: datetime) -> None:
    delivery = _new_delivery(agency, recipient, NotificationDeliveryKind.ALERT, DeliveryStatus.SENT, email.batch, sent_at=now)
    session.add(delivery)
    session.flush()
    for alert in email.notified_alerts:
        session.add(AlertNotification(alert_id=alert.id, notification_recipient_id=recipient.id, email_delivery_id=delivery.id, notified_at=now))
    logger.info(
        "Notification alert email delivered",
        extra={"agency_id": agency.id, "notification_recipient_id": recipient.id, "alert_count": len(email.notified_alerts)},
    )


def _record_report_sent(session: Session, agency: Agency, recipient: NotificationRecipient, email: AlertEmail, now: datetime) -> None:
    session.add(_new_delivery(agency, recipient, NotificationDeliveryKind.REPORT, DeliveryStatus.SENT, email.batch, sent_at=now))
    logger.info("Notification report email delivered", extra={"agency_id": agency.id, "notification_recipient_id": recipient.id})


def _record_failure(
    session: Session, agency: Agency, recipient: NotificationRecipient, kind: NotificationDeliveryKind, batch: EmailBatch, now: datetime
) -> None:
    delivery = _new_delivery(agency, recipient, kind, DeliveryStatus.ERROR, batch, sent_at=None)
    delivery.error_type = "EMAIL_DELIVERY_FAILED"
    delivery.error_message = "Email provider did not accept the notification delivery."
    session.add(delivery)
    session.flush()
    logger.error(
        "Notification email delivery failed",
        extra={"email_delivery_id": delivery.id, "agency_id": agency.id, "notification_recipient_id": recipient.id, "kind": kind.value},
    )
    send_developer_delivery_failure_alert(delivery)


def _new_delivery(
    agency: Agency,
    recipient: NotificationRecipient,
    kind: NotificationDeliveryKind,
    status: DeliveryStatus,
    batch: EmailBatch,
    *,
    sent_at: datetime | None,
) -> EmailDelivery:
    return EmailDelivery(
        agency_id=agency.id,
        notification_recipient_id=recipient.id,
        recipient_email_snapshot=recipient.email,
        kind=kind,
        status=status,
        subject=batch.subject,
        preview_text=_preview_text(batch),
        sent_at=sent_at,
    )


# --------------------------------------------------------------------------- #
# Cadence, quiet hours, reports
# --------------------------------------------------------------------------- #


def _alert_cadence_ready(session: Session, recipient: NotificationRecipient, timezone: str, now: datetime) -> bool:
    frequency = recipient.alert_frequency
    if frequency == AlertEmailFrequency.INSTANT:
        return True
    last_sent = _last_sent_delivery_at(session, recipient.id, NotificationDeliveryKind.ALERT)
    if frequency == AlertEmailFrequency.HOURLY:
        return last_sent is None or now - last_sent >= HOURLY_ALERT_INTERVAL
    local_now = _local_now(timezone, now)
    if local_now.hour < MORNING_EMAIL_LOCAL_HOUR:
        return False
    return last_sent is None or _local_now(timezone, last_sent).date() < local_now.date()


def _already_reported_today(session: Session, recipient: NotificationRecipient, timezone: str, now: datetime) -> bool:
    last_sent = _last_sent_delivery_at(session, recipient.id, NotificationDeliveryKind.REPORT)
    if last_sent is None:
        return False
    return _local_now(timezone, last_sent).date() >= _local_now(timezone, now).date()


def _last_sent_delivery_at(session: Session, recipient_id: int, kind: NotificationDeliveryKind) -> datetime | None:
    return session.scalar(
        select(func.max(EmailDelivery.sent_at)).where(
            EmailDelivery.notification_recipient_id == recipient_id,
            EmailDelivery.kind == kind,
            EmailDelivery.status == DeliveryStatus.SENT,
        )
    )


def _due_report_preferences(recipient: NotificationRecipient, timezone: str, now: datetime, *, force: bool) -> tuple[NotificationPreference, ...]:
    local_now = _local_now(timezone, now)
    if not force and local_now.hour < MORNING_EMAIL_LOCAL_HOUR:
        return ()
    return tuple(preference for preference in due_summary_preferences(local_now) if recipient.preference_enabled(preference.key))


def _report_title(preferences: tuple[NotificationPreference, ...]) -> str:
    if preferences:
        return inventory_summary_title(preferences[-1].label)
    return INVENTORY_SUMMARIES_TITLE


def _in_quiet_hours(recipient: NotificationRecipient, timezone: str, now: datetime) -> bool:
    try:
        quiet_start = _parse_quiet_time(recipient.quiet_start_time)
        quiet_end = _parse_quiet_time(recipient.quiet_end_time)
    except ValueError as exc:
        logger.warning(
            "Notification quiet hours ignored because stored values are invalid",
            extra={"agency_id": recipient.agency_id, "notification_recipient_id": recipient.id, "error": str(exc)},
        )
        return False
    if quiet_start is None or quiet_end is None or quiet_start == quiet_end:
        return False
    return _time_is_quiet(_local_now(timezone, now).time(), quiet_start, quiet_end)


def _parse_quiet_time(value: str | None) -> time | None:
    if not value:
        return None
    hour, minute = (int(part) for part in value.split(":", maxsplit=1))
    return time(hour=hour, minute=minute)


def _time_is_quiet(local_time: time, quiet_start: time, quiet_end: time) -> bool:
    if quiet_start < quiet_end:
        return quiet_start <= local_time < quiet_end
    return local_time >= quiet_start or local_time < quiet_end


def _active_agencies(session: Session, agency_id: int | None = None) -> list[Agency]:
    stmt = select(Agency).where(Agency.active.is_(True)).order_by(Agency.id)
    if agency_id is not None:
        stmt = stmt.where(Agency.id == agency_id)
    return list(session.execute(stmt).scalars().all())


def _display_now(timezone: str, now: datetime) -> str:
    return _local_now(timezone, now).strftime("%B %d, %Y %H:%M")


def _local_now(timezone: str, now: datetime) -> datetime:
    aware = now.replace(tzinfo=UTC) if now.tzinfo is None else now
    return aware.astimezone(ZoneInfo(timezone or "UTC"))


def _now() -> datetime:
    return utc_now_naive()
