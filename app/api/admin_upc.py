"""JSON endpoints for reviewing barcodes no item carries."""

from collections.abc import Callable
from functools import partial
from http import HTTPStatus
from typing import Final

from apiflask import HTTPError
from loguru import logger
from sqlalchemy.orm import Session

from app.api.admin_access import admin_only
from app.api.admin_upc_schema import AddBarcodeRequest, LinkBarcodeRequest
from app.api.blueprint import api_bp
from app.api.constants import AGENCY_ROUTE
from app.inventory.models import validate_upc_code
from app.inventory.upc_review_response import AddedBarcodeResponse, UnknownBarcodeReviewResponse
from app.inventory.upc_service import (
    group_review_unknown_upcs,
    ignore_unknown_upc,
    record_unknown_upc,
    remove_unknown_upc,
    resolve_unknown_upc,
    unignore_unknown_upc,
)
from app.shared.database import get_session

REVIEW_ROUTE: Final[str] = f"{AGENCY_ROUTE}/admin/unknown-barcodes"
ONE_REVIEW_ROUTE: Final[str] = f"{REVIEW_ROUTE}/<int:unknown_upc_id>"
REVIEW_REFUSED_EVENT: Final[str] = "Unknown barcode review refused"

type ReviewChange = Callable[[Session, int, int], None]


@api_bp.get(REVIEW_ROUTE)
@api_bp.output(UnknownBarcodeReviewResponse)
@api_bp.doc(summary="List the barcodes guests scanned that no item carries, grouped by review status")
@admin_only
def list_unknown_barcodes(agency_id: int) -> UnknownBarcodeReviewResponse:
    with get_session() as session:
        return UnknownBarcodeReviewResponse.of(group_review_unknown_upcs(session, agency_id))


@api_bp.post(REVIEW_ROUTE)
@api_bp.input(AddBarcodeRequest)
@api_bp.output(AddedBarcodeResponse, status_code=HTTPStatus.CREATED)
@api_bp.doc(summary="Add a barcode by hand to the review list")
@admin_only
def add_unknown_barcode(agency_id: int, json_data: AddBarcodeRequest) -> AddedBarcodeResponse:
    with get_session() as session:
        try:
            upc = validate_upc_code(json_data.upc)
            status = record_unknown_upc(session, agency_id, upc)
        except ValueError as error:
            logger.info("Admin barcode not recorded: the code was invalid", extra={"agency_id": agency_id, "error": str(error)})
            raise HTTPError(HTTPStatus.UNPROCESSABLE_ENTITY, str(error)) from error
        session.commit()
    logger.info("Barcode added to review by an admin", extra={"agency_id": agency_id, "status": status.value, "admin_action": True})
    return AddedBarcodeResponse.of(upc, status)


@api_bp.post(f"{ONE_REVIEW_ROUTE}/item")
@api_bp.input(LinkBarcodeRequest)
@api_bp.doc(summary="Link a reviewed barcode to an existing item")
@admin_only
def link_unknown_barcode(agency_id: int, unknown_upc_id: int, json_data: LinkBarcodeRequest) -> tuple[str, int]:
    return _apply_review(agency_id, unknown_upc_id, partial(resolve_unknown_upc, item_id=json_data.item_id), "Unknown barcode linked to item")


@api_bp.post(f"{ONE_REVIEW_ROUTE}/ignore")
@api_bp.doc(summary="Move a reviewed barcode to the ignored list")
@admin_only
def ignore_unknown_barcode(agency_id: int, unknown_upc_id: int) -> tuple[str, int]:
    return _apply_review(agency_id, unknown_upc_id, ignore_unknown_upc, "Unknown barcode ignored")


@api_bp.post(f"{ONE_REVIEW_ROUTE}/pending")
@api_bp.doc(summary="Move an ignored barcode back to the pending list")
@admin_only
def unignore_unknown_barcode(agency_id: int, unknown_upc_id: int) -> tuple[str, int]:
    return _apply_review(agency_id, unknown_upc_id, unignore_unknown_upc, "Unknown barcode moved back to pending")


@api_bp.delete(ONE_REVIEW_ROUTE)
@api_bp.doc(summary="Delete a barcode from the review list")
@admin_only
def delete_unknown_barcode(agency_id: int, unknown_upc_id: int) -> tuple[str, int]:
    return _apply_review(agency_id, unknown_upc_id, remove_unknown_upc, "Unknown barcode deleted from review")


def _apply_review(agency_id: int, unknown_upc_id: int, change: ReviewChange, event: str) -> tuple[str, int]:
    """Apply one review decision, answering the refusal the service names when it cannot."""
    with get_session() as session:
        try:
            change(session, agency_id, unknown_upc_id)
        except ValueError as error:
            logger.info(
                REVIEW_REFUSED_EVENT,
                extra={"agency_id": agency_id, "unknown_upc_id": unknown_upc_id, "error": str(error)},
            )
            raise HTTPError(HTTPStatus.UNPROCESSABLE_ENTITY, str(error)) from error
        session.commit()
    logger.info(event, extra={"agency_id": agency_id, "unknown_upc_id": unknown_upc_id, "admin_action": True})
    return "", HTTPStatus.NO_CONTENT
