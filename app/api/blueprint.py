"""The versioned JSON API blueprint and its JSON error responses."""

from http import HTTPStatus

from apiflask import APIBlueprint
from flask import Response, jsonify
from loguru import logger
from werkzeug.exceptions import HTTPException

from app.api.constants import API_VERSION

api_bp = APIBlueprint(API_VERSION, __name__)


@api_bp.errorhandler(HTTPException)
def json_error(error: HTTPException) -> tuple[Response, int]:
    """Keep API failures as JSON; v1 pages keep their HTML error screens."""
    status_code = error.code or HTTPStatus.INTERNAL_SERVER_ERROR
    logger.warning("API request failed", extra={"status_code": status_code, "detail": error.description})
    return jsonify(message=error.description, status_code=status_code), status_code
