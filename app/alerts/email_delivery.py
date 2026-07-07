"""Alert email delivery adapters."""

from pathlib import Path

from flask import current_app, render_template
from loguru import logger

from app.alerts.models import NotificationEmailDelivery
from app.shared.clock import utc_now
from app.shared.email_client import (
    EMAIL_RETRY_DELAYS_SECONDS,
    EmailAttachment,
    OutboundEmail,
    email_configured,
    send_email,
)
from app.shared.file_retention import keep_newest_files

from .schema import EmailBatch

ALERT_FILE_RETENTION_COUNT = 10


def deliver_batch(batch: EmailBatch, *, attachments: tuple[EmailAttachment, ...] = ()) -> bool:
    """Send through the provider, or write files when email config is disabled."""
    text_body = render_template("batch_email.txt", batch=batch)
    html_body = render_template("batch_email.html", batch=batch)
    if not email_configured():
        return _write_batch_file(batch, attachments)

    sent = send_email(
        OutboundEmail(
            subject=batch.subject,
            text_body=text_body,
            html_body=html_body,
            to_email=batch.agency_email,
            attachments=attachments,
        ),
        retry_delays_seconds=EMAIL_RETRY_DELAYS_SECONDS,
    )
    if sent:
        logger.debug(
            "Alert email batch delivered through provider",
            extra={"section_count": len(batch.sections), "summary_count": len(batch.summary)},
        )
    return sent


def deliver_notification_email(delivery: NotificationEmailDelivery) -> bool:
    """Send a stored notification delivery, or write files in local fallback mode."""
    if not email_configured():
        return _write_delivery_file(delivery)

    return send_email(
        OutboundEmail(
            subject=delivery.subject,
            text_body=delivery.body_text,
            html_body=delivery.body_html,
            to_email=delivery.recipient_email_snapshot,
        ),
        retry_delays_seconds=(),
    )


def _write_batch_file(batch: EmailBatch, attachments: tuple[EmailAttachment, ...]) -> bool:
    try:
        html_path = _alert_file_path()
        html_path.write_text(render_template("batch_email.html", batch=batch), encoding="utf-8")
        html_path.with_suffix(".txt").write_text(render_template("batch_email.txt", batch=batch), encoding="utf-8")
        for attachment in attachments:
            html_path.with_name(f"{html_path.stem}_{attachment.filename}").write_bytes(attachment.content_bytes)
        _prune_alert_files(html_path.parent)
        logger.info(
            "Alert email batch written to local files",
            extra={
                "path": str(html_path),
                "section_count": len(batch.sections),
                "summary_count": len(batch.summary),
                "attachment_count": len(attachments),
            },
        )
        return True
    except OSError:
        logger.exception(
            "Alert email batch file write failed",
            extra={"section_count": len(batch.sections), "summary_count": len(batch.summary), "attachment_count": len(attachments)},
        )
        return False


def _write_delivery_file(delivery: NotificationEmailDelivery) -> bool:
    try:
        html_path = _alert_file_path()
        html_path.write_text(delivery.body_html, encoding="utf-8")
        html_path.with_suffix(".txt").write_text(delivery.body_text, encoding="utf-8")
        _prune_alert_files(html_path.parent)
        logger.info(
            "Notification email delivery written to local files",
            extra={
                "notification_email_delivery_id": delivery.id,
                "agency_id": delivery.agency_id,
                "notification_recipient_id": delivery.notification_recipient_id,
                "path": str(html_path),
            },
        )
        return True
    except OSError:
        logger.exception(
            "Notification email delivery file write failed",
            extra={
                "notification_email_delivery_id": delivery.id,
                "agency_id": delivery.agency_id,
                "notification_recipient_id": delivery.notification_recipient_id,
            },
        )
        return False


def _alert_file_path() -> Path:
    alerts_dir = Path(current_app.instance_path) / "alerts"
    alerts_dir.mkdir(parents=True, exist_ok=True)
    stamp = utc_now().strftime("%Y%m%d_%H%M%S")
    path = alerts_dir / f"{stamp}_alert.html"
    index = 1
    while path.exists():
        path = alerts_dir / f"{stamp}_{index}_alert.html"
        index += 1
    return path


def _prune_alert_files(alerts_dir: Path) -> None:
    keep_newest_files(alerts_dir, "*_alert.*", ALERT_FILE_RETENTION_COUNT)
