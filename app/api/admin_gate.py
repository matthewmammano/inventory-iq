"""JSON endpoints for the admin PIN that unlocks the admin screens."""

from http import HTTPStatus

from apiflask import HTTPError
from loguru import logger

from app.api.blueprint import api_bp
from app.api.schema import AdminPinRequest
from app.auth.admin_session import AdminSessionState, clear_admin_session, start_admin_session, touch_admin_session
from app.auth.queries import get_agency
from app.auth.response import AdminSessionResponse
from app.inventory.admin_edit_service import send_temporary_admin_pin
from app.shared.database import get_session
from app.shared.rate_limit import AUTH_RATE_LIMIT, limiter, refused_json_auth_only

ADMIN_SESSION_ROUTE = "/agencies/<int:agency_id>/admin-session"
UNKNOWN_AGENCY_MESSAGE = "Invalid agency."
INVALID_PIN_MESSAGE = "Invalid PIN."  # nosec B105 - user-facing copy, not a credential
TEMPORARY_PIN_FAILED_MESSAGE = "Temporary PIN could not be sent. Try again."  # nosec B105 - user-facing copy, not a credential


@api_bp.get(ADMIN_SESSION_ROUTE)
@api_bp.output(AdminSessionResponse)
@api_bp.doc(summary="Say whether this browser still holds the admin unlock")
def read_admin_session(agency_id: int) -> AdminSessionResponse:
    state = touch_admin_session()
    if state is not AdminSessionState.ACTIVE:
        logger.info("Admin session read as locked", extra={"agency_id": agency_id, "admin_session_state": state})
    return AdminSessionResponse(unlocked=state is AdminSessionState.ACTIVE)


@api_bp.post(ADMIN_SESSION_ROUTE)
@api_bp.input(AdminPinRequest)
@api_bp.output(AdminSessionResponse, status_code=HTTPStatus.CREATED)
@api_bp.doc(summary="Unlock the admin screens with the agency's 4-digit PIN")
@limiter.limit(AUTH_RATE_LIMIT, deduct_when=refused_json_auth_only)
def unlock_admin_session(agency_id: int, json_data: AdminPinRequest) -> AdminSessionResponse:
    with get_session() as session:
        agency = get_agency(agency_id, session)
        if agency is None:
            logger.warning("Admin PIN unlock rejected: unknown agency", extra={"agency_id": agency_id})
            raise HTTPError(HTTPStatus.NOT_FOUND, UNKNOWN_AGENCY_MESSAGE)
        if not agency.check_pin(json_data.pin):
            logger.info("Admin PIN unlock rejected: invalid PIN", extra={"agency_id": agency_id})
            raise HTTPError(HTTPStatus.UNAUTHORIZED, INVALID_PIN_MESSAGE)
    start_admin_session()
    logger.info("Admin PIN unlock succeeded", extra={"agency_id": agency_id})
    return AdminSessionResponse(unlocked=True)


@api_bp.delete(ADMIN_SESSION_ROUTE)
@api_bp.doc(summary="Drop the admin unlock, the way leaving for a guest screen does")
def lock_admin_session(agency_id: int) -> tuple[str, int]:
    clear_admin_session()
    logger.info("Admin unlock dropped", extra={"agency_id": agency_id})
    return "", HTTPStatus.NO_CONTENT


@api_bp.post(f"{ADMIN_SESSION_ROUTE}/temporary-pin")
@api_bp.doc(summary="Email a new temporary admin PIN to the account address")
@limiter.limit(AUTH_RATE_LIMIT)
def email_temporary_admin_pin(agency_id: int) -> tuple[str, int]:
    with get_session() as session:
        agency = get_agency(agency_id, session)
        if agency is None:
            logger.warning("Temporary admin PIN rejected: unknown agency", extra={"agency_id": agency_id})
            raise HTTPError(HTTPStatus.NOT_FOUND, UNKNOWN_AGENCY_MESSAGE)
        if not send_temporary_admin_pin(agency):
            raise HTTPError(HTTPStatus.BAD_GATEWAY, TEMPORARY_PIN_FAILED_MESSAGE)
        session.commit()
    return "", HTTPStatus.ACCEPTED
