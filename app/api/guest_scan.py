"""JSON endpoints behind the guest scan screen."""

from http import HTTPStatus

from apiflask import HTTPError
from loguru import logger

from app.api.blueprint import api_bp
from app.api.schema import ScanRequest, StorageOptionsQuery, UpcLookupQuery
from app.auth.queries import list_top_locations
from app.auth.response import LocationListResponse, LocationResponse
from app.inventory.errors import InventoryError
from app.inventory.item_queries import attach_item_tags, get_item_by_upc
from app.inventory.response import ItemListResponse, ItemResponse, ScanResultResponse, ScanStorageOptionsResponse
from app.inventory.scan_submit_service import (
    ScanSubmitItemNotFoundError,
    ScanSubmitRouteError,
    save_scan_submission,
)
from app.inventory.scan_support import ScanActor, get_scan_permissions, load_scan_storage_choices
from app.inventory.search_payload import build_item_search_payload, load_item_search_payload
from app.shared.database import get_session

AGENCY_ROUTE = "/agencies/<int:agency_id>"
ITEM_NOT_FOUND_MESSAGE = "No item carries that barcode."
SCAN_ITEM_NOT_FOUND_MESSAGE = "That item is not in this agency's inventory."


@api_bp.get(f"{AGENCY_ROUTE}/locations")
@api_bp.output(LocationListResponse)
@api_bp.doc(summary="List the agency's locations")
def list_agency_locations(agency_id: int) -> LocationListResponse:
    with get_session() as session:
        return LocationListResponse([LocationResponse.of(location) for location in list_top_locations(agency_id, session)])


@api_bp.get(f"{AGENCY_ROUTE}/storages")
@api_bp.input(StorageOptionsQuery, location="query")
@api_bp.output(ScanStorageOptionsResponse)
@api_bp.doc(summary="List where a scan may come from and go to")
def list_scan_storages(agency_id: int, query_data: StorageOptionsQuery) -> ScanStorageOptionsResponse:
    permissions = get_scan_permissions(agency_id)
    with get_session() as session:
        choices = load_scan_storage_choices(agency_id, is_admin=False, session=session, agency_location_id=query_data.location_id)
        return ScanStorageOptionsResponse.of(choices, permissions)


@api_bp.get(f"{AGENCY_ROUTE}/items")
@api_bp.output(ItemListResponse)
@api_bp.doc(summary="List the agency's items, most recently scanned first")
def list_agency_items(agency_id: int) -> ItemListResponse:
    with get_session() as session:
        payload = load_item_search_payload(session, agency_id, order_by_last_accessed=True)
    return ItemListResponse([ItemResponse.of(entry) for entry in payload])


@api_bp.get(f"{AGENCY_ROUTE}/items/lookup")
@api_bp.input(UpcLookupQuery, location="query")
@api_bp.output(ItemResponse)
@api_bp.doc(summary="Find one item by a scanned barcode")
def lookup_item_by_upc(agency_id: int, query_data: UpcLookupQuery) -> ItemResponse:
    with get_session() as session:
        item = get_item_by_upc(agency_id, query_data.upc, session=session)
        if item is None:
            logger.info("Barcode lookup found no item", extra={"agency_id": agency_id})
            raise HTTPError(HTTPStatus.NOT_FOUND, ITEM_NOT_FOUND_MESSAGE)
        attach_item_tags(agency_id, [item], session)
        return ItemResponse.of(build_item_search_payload([item])[0])


@api_bp.post(f"{AGENCY_ROUTE}/scans")
@api_bp.input(ScanRequest)
@api_bp.output(ScanResultResponse, status_code=HTTPStatus.CREATED)
@api_bp.doc(summary="Save one scan")
def save_scan(agency_id: int, json_data: ScanRequest) -> ScanResultResponse:
    permissions = get_scan_permissions(agency_id)
    with get_session() as session:
        actor = ScanActor(agency_id=agency_id, is_admin=False, session=session)
        try:
            result = save_scan_submission(actor, request_data=json_data, permissions=permissions, expiration_allocations=json_data.allocations())
        except ScanSubmitItemNotFoundError as error:
            raise HTTPError(HTTPStatus.NOT_FOUND, SCAN_ITEM_NOT_FOUND_MESSAGE) from error
        except ScanSubmitRouteError as error:
            raise HTTPError(HTTPStatus.FORBIDDEN, str(error)) from error
        except (InventoryError, ValueError) as error:
            raise HTTPError(HTTPStatus.UNPROCESSABLE_ENTITY, str(error)) from error
        return ScanResultResponse.of(result)
