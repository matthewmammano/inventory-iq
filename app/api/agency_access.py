"""Every API route under an agency is answered only for that signed-in agency."""

from http import HTTPStatus

from apiflask import HTTPError
from flask import request
from flask_login import current_user
from loguru import logger

from app.api.blueprint import api_bp

AGENCY_VIEW_ARG = "agency_id"
UNAUTHENTICATED_MESSAGE = "Sign in to use the API."
WRONG_AGENCY_MESSAGE = "This agency is not available to you."
INACTIVE_AGENCY_MESSAGE = "This agency is inactive."


@api_bp.before_request
def require_own_agency() -> None:
    """Refuse any agency-scoped request that is not the signed-in agency's own."""
    agency_id = (request.view_args or {}).get(AGENCY_VIEW_ARG)
    if agency_id is None:
        return
    if not current_user.is_authenticated:
        logger.info("API request rejected: not signed in", extra={"agency_id": agency_id, "path": request.path})
        raise HTTPError(HTTPStatus.UNAUTHORIZED, UNAUTHENTICATED_MESSAGE)
    if current_user.id != agency_id:
        logger.warning(
            "API request rejected: agency does not match the signed-in account",
            extra={"agency_id": agency_id, "signed_in_agency_id": current_user.id},
        )
        raise HTTPError(HTTPStatus.FORBIDDEN, WRONG_AGENCY_MESSAGE)
    if not current_user.active:
        logger.warning("API request rejected: agency is inactive", extra={"agency_id": agency_id})
        raise HTTPError(HTTPStatus.FORBIDDEN, INACTIVE_AGENCY_MESSAGE)
