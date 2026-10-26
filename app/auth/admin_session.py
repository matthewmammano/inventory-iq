"""The admin unlock kept in the Flask session, and the idle timeout that ends it."""

from datetime import UTC, datetime
from enum import StrEnum, auto

from flask import session

from app.shared.constants import ADMIN_TIMEOUT

ADMIN_FLAG_KEY = "admin"
ADMIN_LAST_ACTIVE_KEY = "admin_last_active"


class AdminSessionState(StrEnum):
    """Why an admin-only request was allowed or refused."""

    ACTIVE = auto()
    MISSING = auto()
    EXPIRED = auto()


def start_admin_session() -> None:
    session[ADMIN_FLAG_KEY] = True
    session[ADMIN_LAST_ACTIVE_KEY] = datetime.now(UTC).timestamp()


def clear_admin_session() -> None:
    session.pop(ADMIN_FLAG_KEY, None)
    session.pop(ADMIN_LAST_ACTIVE_KEY, None)


def touch_admin_session(timeout_seconds: int = ADMIN_TIMEOUT) -> AdminSessionState:
    """Refuse and clear an unlock that is absent or idle past the timeout; otherwise extend it."""
    if not session.get(ADMIN_FLAG_KEY):
        clear_admin_session()
        return AdminSessionState.MISSING

    now = datetime.now(UTC).timestamp()
    last_active = session.get(ADMIN_LAST_ACTIVE_KEY)
    if not last_active or now - last_active > timeout_seconds:
        clear_admin_session()
        return AdminSessionState.EXPIRED

    session[ADMIN_LAST_ACTIVE_KEY] = now
    return AdminSessionState.ACTIVE
