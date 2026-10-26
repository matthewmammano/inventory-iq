"""JSON endpoints behind the guest scan screen."""

from http import HTTPStatus

from apiflask import HTTPError
from loguru import logger

from app.api.blueprint import api_bp
from app.api.schema import ExpirationOptionsQuery, ScanRequest, ScanRouteQuery, StorageOptionsQuery, UpcLookupQuery
from app.auth.queries import list_top_locations
from app.auth.response import LocationListResponse, LocationResponse
from app.inventory.constants import UNKNOWN_UPC_INVALID_MESSAGE
from app.inventory.errors import InventoryError
from app.inventory.expiration_ui_service import build_expiration_entry_groups, scan_expiration_spec
from app.inventory.item_queries import attach_item_tags, get_agency_item, get_item_by_upc
from app.inventory.response import (
    ExpirationEntryResponse,
    ItemListResponse,
    ItemResponse,
    ScanContextResponse,
    ScanResultResponse,
    ScanStorageOptionsResponse,
    UnknownUpcResponse,
)
from app.inventory.scan_hints import scan_hints
from app.inventory.scan_submit_service import (
    ScanSubmitItemNotFoundError,
    ScanSubmitRouteError,
    save_scan_submission,
)
from app.inventory.scan_support import (
    ScanActor,
    format_scan_location_label,
    get_scan_permissions,
    load_scan_storage_choices,
    operation_from_storage_ids,
    resolve_scan_location,
    validate_scan_route,
)
from app.inventory.search_payload import build_item_search_payload, load_item_search_payload
from app.inventory.upc_service import record_unknown_upc
from app.shared.database import get_session

AGENCY_ROUTE = "/agencies/<int:agency_id>"
ITEM_NOT_FOUND_MESSAGE = "No item carries that barcode."
SCAN_ITEM_NOT_FOUND_MESSAGE = "That item is not in this agency's inventory."
NO_EXPIRATION_ENTRY_MESSAGE = "This scan needs no expiration dates."


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


@api_bp.get(f"{AGENCY_ROUTE}/items/<int:item_id>/scan-context")
@api_bp.input(ScanRouteQuery, location="query")
@api_bp.output(ScanContextResponse)
@api_bp.doc(summary="Describe the item and route the quantity screen is about to save")
def describe_scan_context(agency_id: int, item_id: int, query_data: ScanRouteQuery) -> ScanContextResponse:
    permissions = get_scan_permissions(agency_id)
    with get_session() as session:
        item = get_agency_item(agency_id, item_id, session=session)
        if item is None:
            raise HTTPError(HTTPStatus.NOT_FOUND, SCAN_ITEM_NOT_FOUND_MESSAGE)
        actor = ScanActor(agency_id=agency_id, is_admin=False, session=session)
        route_error = validate_scan_route(actor, query_data.from_storage_id, query_data.to_storage_id, permissions)
        if route_error:
            logger.info("Scan context rejected: route not allowed", extra={"agency_id": agency_id, "item_id": item_id})
            raise HTTPError(HTTPStatus.FORBIDDEN, route_error)
        from_storage = resolve_scan_location(query_data.from_storage_id, agency_id, session=session)
        to_storage = resolve_scan_location(query_data.to_storage_id, agency_id, takeout_allowed=True, session=session)
        operation, _, _ = operation_from_storage_ids(query_data.from_storage_id, query_data.to_storage_id)
        return ScanContextResponse.of(
            item,
            operation,
            format_scan_location_label(from_storage, is_admin=False),
            format_scan_location_label(to_storage, is_admin=False, takeout_allowed=True),
            scan_hints(session, agency_id, operation, item, to_storage),
        )


@api_bp.get(f"{AGENCY_ROUTE}/items/<int:item_id>/expirations")
@api_bp.input(ExpirationOptionsQuery, location="query")
@api_bp.output(ExpirationEntryResponse)
@api_bp.doc(summary="List the expiration dates one scan's quantity may be split across")
def list_scan_expirations(agency_id: int, item_id: int, query_data: ExpirationOptionsQuery) -> ExpirationEntryResponse:
    operation, from_storage_id, to_storage_id = operation_from_storage_ids(query_data.from_storage_id, query_data.to_storage_id)
    spec = scan_expiration_spec(
        operation_type=operation,
        item_id=item_id,
        quantity=query_data.quantity,
        from_storage_id=from_storage_id,
        to_storage_id=to_storage_id,
    )
    if spec is None:
        raise HTTPError(HTTPStatus.NOT_FOUND, NO_EXPIRATION_ENTRY_MESSAGE)
    with get_session() as session:
        groups = [group for group in build_expiration_entry_groups(session, agency_id, [spec]) if group.requires_entry]
        if not groups:
            raise HTTPError(HTTPStatus.NOT_FOUND, NO_EXPIRATION_ENTRY_MESSAGE)
        return ExpirationEntryResponse.of(groups[0])


@api_bp.post(f"{AGENCY_ROUTE}/unknown-barcodes")
@api_bp.input(UpcLookupQuery, location="query")
@api_bp.output(UnknownUpcResponse)
@api_bp.doc(summary="Record a scanned barcode no item carries")
def record_guest_unknown_upc(agency_id: int, query_data: UpcLookupQuery) -> UnknownUpcResponse:
    with get_session() as session:
        try:
            status = record_unknown_upc(session, agency_id, query_data.upc)
        except ValueError as exc:
            logger.info(
                "Unknown guest UPC not recorded: the code was invalid",
                extra={"agency_id": agency_id, "error": str(exc)},
            )
            return UnknownUpcResponse(message=UNKNOWN_UPC_INVALID_MESSAGE)
        session.commit()
        logger.info("Unknown guest UPC recorded", extra={"agency_id": agency_id, "status": status.value})
        return UnknownUpcResponse(message=status.message)
