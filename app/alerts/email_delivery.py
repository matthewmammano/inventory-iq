"""Alert email delivery adapters."""

from __future__ import annotations

from pathlib import Path

from flask import current_app, render_template
from flask_mailman import EmailMultiAlternatives
from loguru import logger

from app.shared.clock import utc_now

from .schema import EmailBatch

MAIL_REQUIRED_KEYS = ("MAIL_SERVER", "MAIL_USERNAME", "MAIL_PASSWORD", "MAIL_DEFAULT_SENDER")


def deliver_batch(batch: EmailBatch) -> bool:
    """Send through SMTP, or write files when mail config is intentionally disabled."""
    if not _mail_enabled():
        return _write_batch_file(batch)

    try:
        msg = EmailMultiAlternatives(
            subject=batch.subject,
            body=render_template("batch_email.txt", batch=batch),
            from_email=current_app.config.get("MAIL_DEFAULT_SENDER"),
            to=[batch.agency_email],
        )
        msg.attach_alternative(render_template("batch_email.html", batch=batch), "text/html")
        msg.send()
        logger.info("Alert email sent")
        return True
    except Exception:
        logger.exception("Alert email send failed")
        return False


def _mail_enabled() -> bool:
    return all(str(current_app.config.get(key) or "").strip() for key in MAIL_REQUIRED_KEYS)


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
