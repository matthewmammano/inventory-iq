"""Alert email delivery adapter: send a composed batch or write it to files."""

from pathlib import Path

from flask import current_app, render_template
from loguru import logger

from app.shared.clock import utc_now
from app.shared.email_client import (
    EMAIL_RETRY_DELAYS_SECONDS,
    EmailAttachment,
    OutboundEmail,
    email_configured,
    send_email,
)
from app.shared.file_retention import keep_newest_groups

from .schema import EmailBatch

ALERT_FILE_RETENTION_COUNT = 10  # sent emails to keep (each is one html/txt pair plus any attachments)


def deliver_batch(
    batch: EmailBatch,
    *,
    attachments: tuple[EmailAttachment, ...] = (),
    retry_delays_seconds: tuple[int, ...] = EMAIL_RETRY_DELAYS_SECONDS,
) -> bool:
    """Send a composed email through the provider, or write files when disabled."""
    text_body = render_template("batch_email.txt", batch=batch)
    html_body = render_template("batch_email.html", batch=batch)
    if not email_configured():
        return _write_batch_file(batch, text_body, html_body, attachments)

    sent = send_email(
        OutboundEmail(
            subject=batch.subject,
            text_body=text_body,
            html_body=html_body,
            to_email=batch.agency_email,
            attachments=attachments,
        ),
        retry_delays_seconds=retry_delays_seconds,
    )
    if sent:
        logger.debug(
            "Alert email batch delivered through provider",
            extra={"section_count": len(batch.sections), "summary_count": len(batch.summary)},
        )
    return sent


def _write_batch_file(
    batch: EmailBatch,
    text_body: str,
    html_body: str,
    attachments: tuple[EmailAttachment, ...],
) -> bool:
    try:
        html_path = _alert_file_path()
        html_path.write_text(html_body, encoding="utf-8")
        html_path.with_suffix(".txt").write_text(text_body, encoding="utf-8")
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
    keep_newest_groups(alerts_dir, "*_alert.html", ALERT_FILE_RETENTION_COUNT)
