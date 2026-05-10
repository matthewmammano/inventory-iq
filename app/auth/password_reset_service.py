"""Password reset PIN creation, validation, and email delivery."""

from __future__ import annotations

import secrets
from datetime import timedelta
from pathlib import Path

from flask import current_app
from flask_mailman import EmailMultiAlternatives
from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.shared.clock import utc_now, utc_now_naive

from .constants import RESET_PIN_DIGITS, RESET_PIN_MAX_ATTEMPTS, RESET_PIN_TTL_MINUTES
from .models import Agencies, PasswordResetPins

MAIL_REQUIRED_KEYS = ("MAIL_SERVER", "MAIL_USERNAME", "MAIL_PASSWORD", "MAIL_DEFAULT_SENDER")


def create_password_reset_pin(session: Session, email: str) -> bool:
    """Create and send a reset PIN when the agency exists; never reveals existence."""
    agency = _active_agency_by_email(session, email)
    if agency is None:
        logger.warning("Password reset requested for unknown or inactive agency")
        return True

    now = utc_now_naive()
    pin = f"{secrets.randbelow(10**RESET_PIN_DIGITS):0{RESET_PIN_DIGITS}d}"
    _clear_open_pins(session, agency.id, now)
    reset_pin = PasswordResetPins(
        agency_id=agency.id,
        expires_at=now + timedelta(minutes=RESET_PIN_TTL_MINUTES),
        created_at=now,
    )
    reset_pin.set_pin(pin)
    session.add(reset_pin)
    session.commit()

    sent = _send_reset_pin(agency.email, pin)
    logger.info(
        "Password reset PIN generated",
        extra={"agency_id": agency.id, "sent": sent},
    )
    return sent


def reset_password_with_pin(
    session: Session,
    email: str,
    pin: str,
    new_password: str,
) -> bool:
    agency = _active_agency_by_email(session, email)
    if agency is None:
        logger.warning("Password reset rejected: unknown or inactive agency")
        return False

    reset_pin = _latest_open_pin(session, agency.id)
    now = utc_now_naive()
    if reset_pin is None or reset_pin.expires_at < now:
        logger.warning(
            "Password reset rejected: expired or missing PIN",
            extra={"agency_id": agency.id},
        )
        return False
    if reset_pin.attempt_count >= RESET_PIN_MAX_ATTEMPTS:
        reset_pin.used_at = now
        session.commit()
        logger.warning("Password reset rejected: attempts exceeded", extra={"agency_id": agency.id})
        return False
    if not reset_pin.check_pin(pin):
        reset_pin.attempt_count += 1
        session.commit()
        logger.warning("Password reset rejected: invalid PIN", extra={"agency_id": agency.id})
        return False

    agency.set_password(new_password)
    reset_pin.used_at = now
    session.commit()
    logger.info("Password reset completed", extra={"agency_id": agency.id})
    return True


def _active_agency_by_email(session: Session, email: str) -> Agencies | None:
    return (
        session.execute(
            select(Agencies).where(Agencies.email == email.strip(), Agencies.active.is_(True))
        )
        .scalars()
        .first()
    )


def _clear_open_pins(session: Session, agency_id: int, now) -> None:
    pins = session.execute(
        select(PasswordResetPins).where(
            PasswordResetPins.agency_id == agency_id,
            PasswordResetPins.used_at.is_(None),
        )
    ).scalars()
    for pin in pins:
        pin.used_at = now


def _latest_open_pin(session: Session, agency_id: int) -> PasswordResetPins | None:
    return (
        session.execute(
            select(PasswordResetPins)
            .where(
                PasswordResetPins.agency_id == agency_id,
                PasswordResetPins.used_at.is_(None),
            )
            .order_by(PasswordResetPins.created_at.desc())
        )
        .scalars()
        .first()
    )


def _send_reset_pin(email: str, pin: str) -> bool:
    body = (
        "Inventory IQ password reset\n\n"
        f"Your reset PIN is: {pin}\n\n"
        f"This PIN expires in {RESET_PIN_TTL_MINUTES} minutes."
    )
    if not _mail_enabled():
        return _write_reset_file(email, body)
    try:
        EmailMultiAlternatives(
            subject="Inventory IQ Password Reset PIN",
            body=body,
            from_email=current_app.config.get("MAIL_DEFAULT_SENDER"),
            to=[email],
        ).send()
        logger.info("Password reset PIN email sent")
        return True
    except Exception:
        logger.exception("Password reset PIN email failed")
        return False


def _mail_enabled() -> bool:
    return all(str(current_app.config.get(key) or "").strip() for key in MAIL_REQUIRED_KEYS)


def _write_reset_file(email: str, body: str) -> bool:
    try:
        reset_dir = Path(current_app.instance_path) / "password_resets"
        reset_dir.mkdir(parents=True, exist_ok=True)
        path = reset_dir / f"{utc_now().strftime('%Y%m%d_%H%M%S_%f')}_reset.txt"
        path.write_text(f"To: {email}\n\n{body}", encoding="utf-8")
        logger.info("Password reset PIN written to file", extra={"path": str(path)})
        return True
    except OSError:
        logger.exception("Password reset PIN file write failed")
        return False
