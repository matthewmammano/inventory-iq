"""JSON endpoints for the account session: who is signed in, signing in, and signing out."""

from http import HTTPStatus
from typing import cast

from apiflask import HTTPError
from flask_login import current_user, login_user, logout_user
from loguru import logger

from app.api.agency_access import UNAUTHENTICATED_MESSAGE
from app.api.blueprint import api_bp
from app.api.schema import SignInRequest
from app.auth.admin_session import clear_admin_session
from app.auth.models import Agency
from app.auth.response import SignedInAgencyResponse
from app.auth.sign_in_service import SignInOutcome, authenticate_agency
from app.shared.database import get_session
from app.shared.email_addresses import email_domain
from app.shared.rate_limit import AUTH_RATE_LIMIT, limiter, refused_json_auth_only

SESSION_ROUTE = "/session"
INVALID_CREDENTIALS_MESSAGE = "Invalid email or password."
PASSWORD_NOT_SET_MESSAGE = "Use the emailed PIN to set your password."  # nosec B105 - user-facing copy, not a credential


@api_bp.get("/me")
@api_bp.output(SignedInAgencyResponse)
@api_bp.doc(summary="Describe the signed-in agency")
def describe_signed_in_agency() -> SignedInAgencyResponse:
    if not current_user.is_authenticated:
        logger.info("API session request rejected: not signed in")
        raise HTTPError(HTTPStatus.UNAUTHORIZED, UNAUTHENTICATED_MESSAGE)
    return SignedInAgencyResponse.of(cast(Agency, current_user))


@api_bp.post(SESSION_ROUTE)
@api_bp.input(SignInRequest)
@api_bp.output(SignedInAgencyResponse, status_code=HTTPStatus.CREATED)
@api_bp.doc(summary="Sign in with an account email and password")
@limiter.limit(AUTH_RATE_LIMIT, deduct_when=refused_json_auth_only)
def sign_in(json_data: SignInRequest) -> SignedInAgencyResponse:
    with get_session() as session:
        result = authenticate_agency(session, json_data.email, json_data.password)
        if result.outcome is SignInOutcome.PASSWORD_NOT_SET:
            logger.info("API sign-in redirected: password has not been set", extra={"agency_id": result.agency_id})
            raise HTTPError(HTTPStatus.CONFLICT, PASSWORD_NOT_SET_MESSAGE)
        if result.outcome is SignInOutcome.REJECTED or result.agency is None:
            logger.warning(
                "API sign-in rejected: invalid credentials",
                extra={"email_domain": email_domain(json_data.email), "agency_id": result.agency_id},
            )
            raise HTTPError(HTTPStatus.UNAUTHORIZED, INVALID_CREDENTIALS_MESSAGE)
        login_user(result.agency)
        logger.info("API sign-in succeeded", extra={"agency_id": result.agency.id})
        return SignedInAgencyResponse.of(result.agency)


@api_bp.delete(SESSION_ROUTE)
@api_bp.doc(summary="Sign out of the account and drop any admin unlock")
def sign_out() -> tuple[str, int]:
    agency_id = current_user.id if current_user.is_authenticated else None
    clear_admin_session()
    logout_user()
    logger.info("API sign-out completed", extra={"agency_id": agency_id})
    return "", HTTPStatus.NO_CONTENT
