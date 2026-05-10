"""Device-level default location persistence."""

import hashlib
import secrets
from datetime import UTC, datetime

from flask import Response, request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import AgencyDevices, AgencyLocations
from app.shared.database import managed_session

DEVICE_COOKIE = "inventory_iq_device"
DEVICE_COOKIE_AGE_SECONDS = 60 * 60 * 24 * 365


def current_device_token() -> str:
    return request.cookies.get(DEVICE_COOKIE) or secrets.token_urlsafe(32)


def set_device_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        DEVICE_COOKIE,
        token,
        max_age=DEVICE_COOKIE_AGE_SECONDS,
        httponly=True,
        samesite="Lax",
        secure=request.is_secure,
    )


def get_device_location_id(agency_id: int, session: Session | None = None) -> int | None:
    token = request.cookies.get(DEVICE_COOKIE)
    if not token:
        return None
    with managed_session(session) as s:
        device = _get_device(s, agency_id, token)
        if not device or not device.active or not device.location:
            return None
        return device.agency_location_id


def get_or_create_device(agency_id: int, token: str, session: Session) -> AgencyDevices:
    device = _get_device(session, agency_id, token)
    now = datetime.now(UTC)
    if device:
        device.last_seen_at = now
        session.add(device)
        return device
    device = AgencyDevices(
        agency_id=agency_id,
        device_token_hash=_hash_token(agency_id, token),
        last_seen_at=now,
        created_at=now,
        updated_at=now,
    )
    session.add(device)
    session.flush()
    return device


def save_device_location(
    agency_id: int,
    token: str,
    agency_location_id: int | None,
    session: Session,
) -> AgencyDevices:
    if agency_location_id is not None:
        location = (
            session.execute(
                select(AgencyLocations).where(
                    AgencyLocations.id == agency_location_id,
                    AgencyLocations.agency_id == agency_id,
                )
            )
            .scalars()
            .first()
        )
        if location is None:
            raise ValueError("Location not found")

    device = get_or_create_device(agency_id, token, session)
    device.agency_location_id = agency_location_id
    device.updated_at = datetime.now(UTC)
    session.add(device)
    return device


def _get_device(session: Session, agency_id: int, token: str) -> AgencyDevices | None:
    return (
        session.execute(
            select(AgencyDevices).where(
                AgencyDevices.agency_id == agency_id,
                AgencyDevices.device_token_hash == _hash_token(agency_id, token),
            )
        )
        .scalars()
        .first()
    )


def _hash_token(agency_id: int, token: str) -> str:
    return hashlib.sha256(f"{agency_id}:{token}".encode()).hexdigest()
