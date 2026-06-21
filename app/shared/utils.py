"""Shared utilities for route parsing and validation."""

from datetime import UTC, datetime

from flask import flash, request, session, url_for
from flask_login import current_user
from loguru import logger

from app.auth.queries import get_agency_by_display_name
from app.shared.constants import ADMIN_TIMEOUT
from app.shared.database import get_session
from app.shared.validators import parse_optional_int  # noqa: F401 (re-exported)


def parse_bool(value, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).lower() in ("true", "1", "yes", "on")


def is_static_request() -> bool:
    return request.endpoint is not None and "static" in request.endpoint


def get_squad_from_request() -> str | None:
    return request.view_args.get("squad") if request.view_args else None


def validate_squad_access(squad: str) -> str | None:
    """Return redirect URL on failure, None on success."""
    if not squad:
        logger.warning("Squad access rejected: missing squad")
        flash("Squad name is required.", "warning")
        return url_for("auth.login")
    if current_user.is_authenticated and current_user.display_name == squad:
        if not current_user.active:
            logger.warning(
                "Squad access rejected: inactive current user squad",
                extra={"agency_id": current_user.id, "squad": squad},
            )
            flash("This squad is inactive.", "warning")
            return url_for("auth.login")
        return None
    with get_session() as s:
        agency = get_agency_by_display_name(squad, s)
    if not agency:
        logger.warning("Squad access rejected: squad name was not found", extra={"squad": squad})
        flash("Invalid squad name.", "error")
        return url_for("auth.login")
    if not agency.active:
        logger.warning(
            "Squad access rejected: inactive squad",
            extra={"agency_id": agency.id, "squad": squad},
        )
        flash("This squad is inactive.", "warning")
        return url_for("auth.login")
    return None


def validate_admin_session(squad: str, timeout_seconds: int = ADMIN_TIMEOUT) -> str | None:
    """Return redirect URL on failure, None on success."""
    if not session.get("admin"):
        session.pop("admin", None)
        session.pop("admin_last_active", None)
        logger.warning(
            "Admin session rejected: missing",
            extra={"agency_id": getattr(current_user, "id", None), "squad": squad},
        )
        flash("Admin session not found. Please log in with your PIN.", "warning")
        return url_for("guest.index", squad=squad)

    now = datetime.now(UTC).timestamp()
    last_active = session.get("admin_last_active")
    if not last_active or now - last_active > timeout_seconds:
        session.pop("admin", None)
        session.pop("admin_last_active", None)
        logger.warning(
            "Admin session rejected: expired",
            extra={"agency_id": getattr(current_user, "id", None), "squad": squad},
        )
        flash("Admin session expired. Please log in with your PIN again.", "warning")
        return url_for("guest.index", squad=squad)

    session["admin_last_active"] = now
    return None
