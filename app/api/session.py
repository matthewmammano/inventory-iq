"""The JSON endpoint that tells the app shell which agency is signed in."""

from http import HTTPStatus
from typing import cast

from apiflask import HTTPError
from flask_login import current_user
from loguru import logger

from app.api.agency_access import UNAUTHENTICATED_MESSAGE
from app.api.blueprint import api_bp
from app.auth.models import Agency
from app.auth.response import SignedInAgencyResponse


@api_bp.get("/me")
@api_bp.output(SignedInAgencyResponse)
@api_bp.doc(summary="Describe the signed-in agency")
def describe_signed_in_agency() -> SignedInAgencyResponse:
    if not current_user.is_authenticated:
        logger.info("API session request rejected: not signed in")
        raise HTTPError(HTTPStatus.UNAUTHORIZED, UNAUTHENTICATED_MESSAGE)
    return SignedInAgencyResponse.of(cast(Agency, current_user))
