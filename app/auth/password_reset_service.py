"""Password reset PIN creation, validation, and email delivery."""

import secrets
from datetime import timedelta

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.shared.clock import utc_now_naive
from app.shared.email_client import OutboundEmail, send_email

from .constants import RESET_PIN_DIGITS, RESET_PIN_MAX_ATTEMPTS, RESET_PIN_TTL_MINUTES
from .models import Agencies, PasswordResetPins


def create_password_reset_pin(session: Session, email: str) -> bool:
    """Create and send a reset PIN when the agency exists; never reveals existence."""
    agency = _active_agency_by_email(session, email)
    if agency is None:
        logger.debug("Password reset request ignored for unknown or inactive agency")
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
    if sent:
        logger.info(
            "Password reset PIN created and delivered to agency email",
            extra={"agency_id": agency.id},
        )
    else:
        logger.warning("Password reset PIN created but email delivery failed", extra={"agency_id": agency.id})
    return sent


def reset_password_with_pin(
    session: Session,
    email: str,
    pin: str,
    new_password: str,
) -> bool:
    agency = _active_agency_by_email(session, email)
    if agency is None:
        logger.warning("Password reset rejected: email does not match an active agency")
        return False

    reset_pin = _latest_open_pin(session, agency.id)
    now = utc_now_naive()
    if reset_pin is None or reset_pin.expires_at < now:
        logger.warning(
            "Password reset rejected: PIN is missing or expired",
            extra={"agency_id": agency.id},
        )
        return False
    if reset_pin.attempt_count >= RESET_PIN_MAX_ATTEMPTS:
        reset_pin.used_at = now
        session.commit()
        logger.warning("Password reset rejected: too many incorrect PIN attempts", extra={"agency_id": agency.id})
        return False
    if not reset_pin.check_pin(pin):
        reset_pin.attempt_count += 1
        session.commit()
        logger.warning("Password reset rejected: incorrect PIN", extra={"agency_id": agency.id})
        return False

    agency.set_password(new_password)
    reset_pin.used_at = now
    session.commit()
    logger.info("Password reset completed for agency account", extra={"agency_id": agency.id})
    return True


def _active_agency_by_email(session: Session, email: str) -> Agencies | None:
    return session.execute(select(Agencies).where(Agencies.email == email.strip(), Agencies.active.is_(True))).scalars().first()


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
    body = f"Inventory IQ password reset\n\nYour reset PIN is: {pin}\n\nThis PIN expires in {RESET_PIN_TTL_MINUTES} minutes."
    sent = send_email(
        OutboundEmail(
            subject="Inventory IQ Password Reset PIN",
            text_body=body,
            to_email=email,
        )
    )
    return sent
