"""HTTPS email delivery adapter.

All app email sends go through this small provider boundary instead of
scattered mail code.
"""

import json
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import HTTPSHandler, Request, build_opener

from flask import current_app
from loguru import logger

EMAIL_SEND_ATTEMPTS = 2


@dataclass(frozen=True)
class OutboundEmail:
    """Minimal email payload used by auth, alerts, and maintenance reports."""

    subject: str
    text_body: str
    to_email: str
    html_body: str | None = None


def email_configured() -> bool:
    """Return whether real email delivery is configured."""
    return bool(
        _config("EMAIL_API_URL") and _config("EMAIL_API_KEY") and _config("EMAIL_SENDER_EMAIL")
    )


def send_email(email: OutboundEmail) -> bool:
    """Send one email through the configured HTTPS email provider."""
    api_url = _config("EMAIL_API_URL")
    api_key = _config("EMAIL_API_KEY")
    sender_email = _config("EMAIL_SENDER_EMAIL")
    if not api_url or not api_key or not sender_email:
        logger.error("Email provider config missing")
        return False

    payload = {
        "sender": {"email": sender_email, "name": _config("EMAIL_SENDER_NAME") or "Inventory IQ"},
        "to": [{"email": email.to_email}],
        "subject": email.subject,
        "textContent": email.text_body,
    }
    if email.html_body:
        payload["htmlContent"] = email.html_body

    request = Request(
        api_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "accept": "application/json",
            "api-key": api_key,
            "content-type": "application/json",
        },
        method="POST",
    )
    for attempt in range(1, EMAIL_SEND_ATTEMPTS + 1):
        result = _send_request(request, attempt)
        if result is not None:
            return result
    return False


def _send_request(request: Request, attempt: int) -> bool | None:
    try:
        with build_opener(HTTPSHandler()).open(request, timeout=_timeout_seconds()) as response:
            if 200 <= response.status < 300:
                logger.info("Email sent")
                return True
            if attempt < EMAIL_SEND_ATTEMPTS:
                logger.warning(
                    "Email retry queued",
                    extra={"status": response.status, "attempt": attempt},
                )
                return None
            logger.error("Email failed", extra={"status": response.status})
            return False
    except HTTPError as exc:
        if exc.code != 429 and 400 <= exc.code < 500:
            logger.error("Email rejected", extra={"status": exc.code})
            return False
        if attempt < EMAIL_SEND_ATTEMPTS:
            logger.warning(
                "Email retry queued",
                extra={"status": exc.code, "attempt": attempt},
            )
            return None
        logger.error("Email rejected", extra={"status": exc.code})
        return False
    except (TimeoutError, URLError, OSError) as exc:
        if attempt < EMAIL_SEND_ATTEMPTS:
            logger.warning(
                "Email retry queued",
                extra={"error": type(exc).__name__, "attempt": attempt},
            )
            return None
        logger.exception("Email request failed")
        return False


def _config(key: str) -> str:
    return str(current_app.config.get(key) or "").strip()


def _timeout_seconds() -> int:
    return int(current_app.config.get("EMAIL_TIMEOUT_SECONDS") or 4)
