"""HTTPS email delivery adapter.

All app email sends go through this small provider boundary instead of
scattered mail code.
"""

import json
import time
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPSHandler, Request, build_opener

from flask import current_app
from loguru import logger

EMAIL_RETRY_DELAYS_SECONDS = (5, 15, 30, 60)


@dataclass(frozen=True)
class OutboundEmail:
    """Minimal email payload used by auth, alerts, and maintenance reports."""

    subject: str
    text_body: str
    to_email: str
    html_body: str | None = None


def email_configured() -> bool:
    """Return whether real email delivery is configured."""
    return bool(_config("EMAIL_API_URL") and _config("EMAIL_API_KEY") and _config("EMAIL_SENDER_EMAIL"))


def log_email_config_status(config) -> None:
    """Log email delivery mode without exposing provider secrets."""
    api_url = str(config.get("EMAIL_API_URL") or "").strip()
    api_key_set = bool(config.get("EMAIL_API_KEY"))
    sender_email = str(config.get("EMAIL_SENDER_EMAIL") or "").strip()
    configured = bool(api_url and api_key_set and sender_email)
    logger.info(
        f"Email delivery: mode={'provider' if configured else 'file_fallback'} "
        f"host={urlparse(api_url).netloc or 'missing'} key_set={api_key_set} "
        f"sender={_recipient_domain(sender_email)} "
        f"timeout={int(config.get('EMAIL_TIMEOUT_SECONDS') or 4)}s"
    )


def send_email(
    email: OutboundEmail,
    *,
    retry_delays_seconds: tuple[int, ...] = (),
) -> bool:
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
    max_attempts = len(retry_delays_seconds) + 1
    recipient_domain = _recipient_domain(email.to_email)
    for attempt in range(1, max_attempts + 1):
        result = _send_request(request, attempt, max_attempts, recipient_domain, retry_delays_seconds)
        if result is not None:
            return result
        time.sleep(retry_delays_seconds[attempt - 1])
    return False


def _send_request(
    request: Request,
    attempt: int,
    max_attempts: int,
    recipient_domain: str,
    retry_delays_seconds: tuple[int, ...],
) -> bool | None:
    try:
        with build_opener(HTTPSHandler()).open(request, timeout=_timeout_seconds()) as response:
            if 200 <= response.status < 300:
                logger.info(f"Email sent: domain={recipient_domain} attempt={attempt}")
                return True
            if attempt < max_attempts:
                _log_retry(
                    recipient_domain,
                    attempt,
                    max_attempts,
                    retry_delays_seconds[attempt - 1],
                    f"status={response.status}",
                )
                return None
            logger.error(f"Email failed: domain={recipient_domain} status={response.status}")
            return False
    except HTTPError as exc:
        message = _http_error_message(exc)
        if exc.code != 429 and 400 <= exc.code < 500:
            logger.error(f"Email rejected: domain={recipient_domain} status={exc.code} " f"provider_message={message}")
            return False
        if attempt < max_attempts:
            _log_retry(
                recipient_domain,
                attempt,
                max_attempts,
                retry_delays_seconds[attempt - 1],
                f"status={exc.code} provider_message={message}",
            )
            return None
        logger.error(f"Email rejected: domain={recipient_domain} status={exc.code} " f"provider_message={message}")
        return False
    except (TimeoutError, URLError, OSError) as exc:
        if attempt < max_attempts:
            _log_retry(
                recipient_domain,
                attempt,
                max_attempts,
                retry_delays_seconds[attempt - 1],
                f"error={type(exc).__name__}",
            )
            return None
        logger.exception(f"Email request failed: domain={recipient_domain} error={type(exc).__name__}")
        return False


def _recipient_domain(email_address: str) -> str:
    _, _, domain = email_address.partition("@")
    return domain or "unknown"


def _log_retry(
    recipient_domain: str,
    attempt: int,
    max_attempts: int,
    delay_seconds: int,
    reason: str,
) -> None:
    logger.warning(f"Email retry: domain={recipient_domain} {reason} " f"attempt={attempt}/{max_attempts} delay={delay_seconds}s")


def _http_error_message(exc: HTTPError) -> str:
    try:
        return exc.read(300).decode("utf-8", errors="replace")
    except OSError:
        return ""


def _config(key: str) -> str:
    return str(current_app.config.get(key) or "").strip()


def _timeout_seconds() -> int:
    return int(current_app.config.get("EMAIL_TIMEOUT_SECONDS") or 4)
