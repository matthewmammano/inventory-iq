"""Alert email delivery adapters."""

from __future__ import annotations

from pathlib import Path

from flask import current_app, render_template
from loguru import logger

from app.shared.brevo_email import OutboundEmail, brevo_configured, send_email
from app.shared.clock import utc_now

from .schema import EmailBatch


def deliver_batch(batch: EmailBatch) -> bool:
    """Send through Brevo, or write files when email config is intentionally disabled."""
    text_body = render_template("batch_email.txt", batch=batch)
    html_body = render_template("batch_email.html", batch=batch)
    if not brevo_configured():
        return _write_batch_file(batch)

    sent = send_email(
        OutboundEmail(
            subject=batch.subject,
            text_body=text_body,
            html_body=html_body,
            to_email=batch.agency_email,
        )
    )
    if sent:
        logger.info("Alert email sent")
    return sent


def _write_batch_file(batch: EmailBatch) -> bool:
    try:
        html_path = _alert_file_path()
        html_path.write_text(render_template("batch_email.html", batch=batch), encoding="utf-8")
        html_path.with_suffix(".txt").write_text(
            render_template("batch_email.txt", batch=batch), encoding="utf-8"
        )
        logger.info("Alert email written to file", extra={"path": str(html_path)})
        return True
    except OSError:
        logger.exception("Alert email file write failed")
        return False


def _alert_file_path() -> Path:
    alerts_dir = Path(current_app.instance_path) / "alerts"
    alerts_dir.mkdir(parents=True, exist_ok=True)
    stamp = utc_now().strftime("%Y%m%d_%H%M%S_%f")
    path = alerts_dir / f"{stamp}_alert.html"
    index = 1
    while path.exists():
        path = alerts_dir / f"{stamp}_{index}_alert.html"
        index += 1
    return path
