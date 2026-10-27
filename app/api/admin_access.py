"""Admin-only JSON routes are answered only while this browser holds the admin PIN unlock."""

from collections.abc import Callable
from http import HTTPStatus

from apiflask import HTTPError
from flask import current_app, request
from loguru import logger

from app.api.blueprint import api_bp
from app.auth.admin_session import AdminSessionState, touch_admin_session

ADMIN_LOCKED_MESSAGE = "Unlock admin with your PIN to do that."
ADMIN_ONLY_ATTRIBUTE = "requires_admin_unlock"


def admin_only[**P, R](view: Callable[P, R]) -> Callable[P, R]:
    """Mark a route as answerable only while the admin PIN unlock is live."""
    setattr(view, ADMIN_ONLY_ATTRIBUTE, True)
    return view


@api_bp.before_request
def require_admin_unlock() -> None:
    """Refuse a marked route before its body is parsed, so a locked browser is never told what it got wrong."""
    view = current_app.view_functions.get(request.endpoint or "")
    if not getattr(view, ADMIN_ONLY_ATTRIBUTE, False):
        return
    state = touch_admin_session()
    if state is not AdminSessionState.ACTIVE:
        logger.info("Admin API request refused: admin is locked", extra={"admin_session_state": state, "path": request.path})
        raise HTTPError(HTTPStatus.FORBIDDEN, ADMIN_LOCKED_MESSAGE)
