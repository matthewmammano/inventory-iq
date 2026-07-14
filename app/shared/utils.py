"""Shared utilities for route parsing and validation."""

from datetime import UTC, datetime

from flask import flash, request, session, url_for
from flask_login import current_user
from loguru import logger

from app.auth.queries import get_agency
from app.shared.constants import ADMIN_TIMEOUT
from app.shared.database import get_session


def parse_bool(value, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).lower() in ("true", "1", "yes", "on")


def is_static_request() -> bool:
    return request.endpoint is not None and "static" in request.endpoint


def get_agency_id_from_request() -> int | None:
    return request.view_args.get("agency_id") if request.view_args else None


def validate_agency_access(agency_id: int | None) -> str | None:
    """Return redirect URL on failure, None on success."""
    if agency_id is None:
        logger.info("Agency access rejected: missing agency_id")
        flash("Agency is required.", "warning")
        return url_for("auth.login")
    if current_user.is_authenticated and current_user.id == agency_id:
        if not current_user.active:
            logger.warning("Agency access rejected: inactive current user", extra={"agency_id": agency_id})
            flash("This agency is inactive.", "warning")
            return url_for("auth.login")
        return None
    with get_session() as s:
        agency = get_agency(agency_id, s)
    if not agency:
        logger.warning("Agency access rejected: unknown agency", extra={"agency_id": agency_id})
        flash("Invalid agency.", "error")
        return url_for("auth.login")
    if not agency.active:
        logger.warning("Agency access rejected: inactive agency", extra={"agency_id": agency_id})
        flash("This agency is inactive.", "warning")
        return url_for("auth.login")
    return None


def validate_admin_session(agency_id: int, timeout_seconds: int = ADMIN_TIMEOUT) -> str | None:
    """Return redirect URL on failure, None on success."""
    if not session.get("admin"):
        session.pop("admin", None)
        session.pop("admin_last_active", None)
        logger.info("Admin session rejected: missing", extra={"agency_id": agency_id})
        flash("Admin PIN required.", "warning")
        return url_for("guest.index", agency_id=agency_id)

    now = datetime.now(UTC).timestamp()
    last_active = session.get("admin_last_active")
    if not last_active or now - last_active > timeout_seconds:
        session.pop("admin", None)
        session.pop("admin_last_active", None)
        logger.info("Admin session rejected: expired", extra={"agency_id": agency_id})
        flash("Admin session expired. Enter your PIN again.", "warning")
        return url_for("guest.index", agency_id=agency_id)

    session["admin_last_active"] = now
    return None
