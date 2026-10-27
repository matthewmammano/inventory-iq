"""JSON endpoints for bulk editing a location's stock."""

from http import HTTPStatus

from apiflask import HTTPError
from loguru import logger
from sqlalchemy.orm import Session

from app.api.admin_access import admin_only
from app.api.admin_bulk_schema import BulkEditRequest
from app.api.blueprint import api_bp
from app.api.constants import AGENCY_ROUTE
from app.inventory.bulk_edit_service import (
    BulkEditData,
    BulkEditEmptyError,
    BulkEditRequiredCountError,
    BulkEditUnknownCellError,
    bulk_dating_groups,
    groups_still_needing_dates,
    save_bulk_edit,
    validate_bulk_edit,
)
from app.inventory.bulk_location_service import (
    load_location_quantity_grid,
    required_count_storage_ids,
    stale_count_days,
    suggested_restock_item_ids,
)
from app.inventory.bulk_response import BulkDatingRequiredResponse, BulkEditGridResponse, BulkEditSaveResponse
from app.inventory.errors import InventoryError
from app.shared.database import get_session

BULK_EDIT_ROUTE = f"{AGENCY_ROUTE}/locations/<int:agency_location_id>/bulk-edit"
UNKNOWN_LOCATION_MESSAGE = "Choose a valid location."
DATING_REQUIRED_MESSAGE = "Enter expiration dates for the tracked items, then submit the same draft again."
SAVE_FAILED_MESSAGE = "Bulk action could not be saved. Try again."


@api_bp.get(BULK_EDIT_ROUTE)
@api_bp.output(BulkEditGridResponse)
@api_bp.doc(summary="Read one location's bulk-edit grid of items, storages, and current quantities")
@admin_only
def read_bulk_edit_grid(agency_id: int, agency_location_id: int) -> BulkEditGridResponse:
    with get_session() as session:
        grid = load_location_quantity_grid(session, agency_id, agency_location_id)
        if grid is None:
            raise _unknown_location(agency_id, agency_location_id)
        return BulkEditGridResponse.of(
            grid,
            required=required_count_storage_ids(session, agency_id, agency_location_id, grid.items),
            suggested_restock_item_ids=suggested_restock_item_ids(session, agency_id, agency_location_id, grid.items),
            stale_count_days=stale_count_days(session, agency_id),
        )


@api_bp.post(BULK_EDIT_ROUTE)
@api_bp.input(BulkEditRequest)
@api_bp.output(BulkEditSaveResponse, status_code=HTTPStatus.CREATED)
@api_bp.doc(
    summary="Save one bulk submission of counts and restocks",
    responses={HTTPStatus.CONFLICT: {"description": "Tracked items still need their expiration dates"}},
)
@admin_only
def save_bulk_edit_submission(agency_id: int, agency_location_id: int, json_data: BulkEditRequest) -> BulkEditSaveResponse:
    data = json_data.to_bulk_edit_data()
    with get_session() as session:
        grid = load_location_quantity_grid(session, agency_id, agency_location_id)
        if grid is None:
            raise _unknown_location(agency_id, agency_location_id)
        try:
            validate_bulk_edit(session, agency_id=agency_id, grid=grid, data=data)
        except (BulkEditUnknownCellError, BulkEditRequiredCountError) as error:
            logger.info(
                "Bulk action rejected before saving",
                extra={"agency_id": agency_id, "agency_location_id": agency_location_id, "reason": type(error).__name__},
            )
            raise HTTPError(HTTPStatus.UNPROCESSABLE_ENTITY, str(error)) from error

        undated = groups_still_needing_dates(bulk_dating_groups(session, agency_id, data), data)
        if undated:
            logger.info(
                "Bulk action held back for expiration dates",
                extra={"agency_id": agency_id, "agency_location_id": agency_location_id, "undated_cell_count": len(undated)},
            )
            raise HTTPError(
                HTTPStatus.CONFLICT,
                DATING_REQUIRED_MESSAGE,
                extra_data=BulkDatingRequiredResponse.of(undated).model_dump(mode="json"),
            )
        return _save(session, agency_id, agency_location_id, data)


def _save(session: Session, agency_id: int, agency_location_id: int, data: BulkEditData) -> BulkEditSaveResponse:
    context = {"agency_id": agency_id, "agency_location_id": agency_location_id, "item_count": len(data.item_ids)}
    try:
        result = save_bulk_edit(session, agency_id=agency_id, agency_location_id=agency_location_id, data=data)
    except BulkEditEmptyError as error:
        logger.info("Bulk action rejected: no count or restock entries submitted", extra=context)
        raise HTTPError(HTTPStatus.UNPROCESSABLE_ENTITY, str(error)) from error
    except (InventoryError, ValueError) as error:
        session.rollback()  # the action rows are already flushed when an allocation total is refused
        logger.info("Bulk action rejected: expiration allocations were not accepted", extra={**context, "error": str(error)})
        raise HTTPError(HTTPStatus.UNPROCESSABLE_ENTITY, str(error)) from error
    except Exception as error:
        session.rollback()
        logger.exception("Bulk inventory changes could not be saved", extra=context)
        raise HTTPError(HTTPStatus.INTERNAL_SERVER_ERROR, SAVE_FAILED_MESSAGE) from error

    logger.info(
        "Bulk inventory changes saved",
        extra={
            **context,
            "count_entry_count": result.count_entry_count,
            "restock_entry_count": result.restock_entry_count,
            "entry_count": result.total_entry_count,
        },
    )
    return BulkEditSaveResponse.of(result, agency_location_id)


def _unknown_location(agency_id: int, agency_location_id: int) -> HTTPError:
    logger.warning(
        "Bulk action rejected: requested location was not found",
        extra={"agency_id": agency_id, "agency_location_id": agency_location_id},
    )
    return HTTPError(HTTPStatus.NOT_FOUND, UNKNOWN_LOCATION_MESSAGE)
