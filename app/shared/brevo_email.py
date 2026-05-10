"""Brevo HTTPS email delivery adapter."""

from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import HTTPSHandler, Request, build_opener

from flask import current_app
from loguru import logger

BREVO_SEND_URL = "https://api.brevo.com/v3/smtp/email"


@dataclass(frozen=True)
class OutboundEmail:
    subject: str
    text_body: str
    to_email: str
    html_body: str | None = None


def brevo_configured() -> bool:
    return bool(_config("BREVO_API_KEY") and _config("BREVO_SENDER_EMAIL"))


def send_email(email: OutboundEmail) -> bool:
    """Send one email through Brevo's HTTPS API."""
    api_key = _config("BREVO_API_KEY")
    sender_email = _config("BREVO_SENDER_EMAIL")
    if not api_key or not sender_email:
        logger.error("Brevo email config missing")
        return False

    payload = {
        "sender": {"email": sender_email, "name": _config("BREVO_SENDER_NAME") or "Inventory IQ"},
        "to": [{"email": email.to_email}],
        "subject": email.subject,
        "textContent": email.text_body,
    }
    if email.html_body:
        payload["htmlContent"] = email.html_body

    request = Request(
        BREVO_SEND_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "accept": "application/json",
            "api-key": api_key,
            "content-type": "application/json",
        },
        method="POST",
    )
    try:
        with build_opener(HTTPSHandler()).open(request, timeout=_timeout_seconds()) as response:
            if 200 <= response.status < 300:
                logger.info("Brevo email sent")
                return True
            logger.error("Brevo email failed", extra={"status": response.status})
            return False
    except HTTPError as exc:
        logger.error("Brevo email rejected", extra={"status": exc.code})
        return False
    except (TimeoutError, URLError, OSError):
        logger.exception("Brevo email request failed")
        return False


def _config(key: str) -> str:
    return str(current_app.config.get(key) or "").strip()


def _timeout_seconds() -> int:
    return int(current_app.config.get("BREVO_TIMEOUT_SECONDS") or 4)
