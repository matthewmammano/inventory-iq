"""JSON endpoints for the admin dashboard, settings, and the counts still waiting on expiration dates."""

from http import HTTPStatus

from apiflask import HTTPError
from loguru import logger
from sqlalchemy.orm import Session

from app.api.admin_access import admin_only
from app.api.admin_overview_schema import AdminSettingsRequest, ExpirationCorrectionsRequest
from app.api.blueprint import api_bp
from app.api.constants import AGENCY_ROUTE
from app.auth.models import Agency
from app.inventory.admin_edit_service import save_admin_settings
from app.inventory.dashboard_service import attention_tiles
from app.inventory.expiration_service import ExpirationAllocation
from app.inventory.expiration_ui_service import (
    ExpirationEntryGroup,
    pending_expiration_corrections,
    save_expiration_corrections,
    sort_expiration_groups,
    validate_group_allocations,
)
from app.inventory.overview_response import (
    AdminSettingsResponse,
    AttentionTileListResponse,
    AttentionTileResponse,
    ExpirationCorrectionResultResponse,
    PendingExpirationGroupResponse,
    PendingExpirationListResponse,
)
from app.shared.database import get_session

DASHBOARD_ROUTE = f"{AGENCY_ROUTE}/admin/dashboard"
SETTINGS_ROUTE = f"{AGENCY_ROUTE}/admin/settings"
PENDING_EXPIRATIONS_ROUTE = f"{AGENCY_ROUTE}/admin/pending-expirations"

UNKNOWN_AGENCY_MESSAGE = "Invalid agency."
NOTHING_PENDING_MESSAGE = "No missing expiration dates need review."
UNANSWERED_PAIRS_MESSAGE = "Send one correction for every item and storage still waiting on dates."
UNKNOWN_PAIR_MESSAGE = "A correction named an item and storage that is not waiting on dates."


@api_bp.get(DASHBOARD_ROUTE)
@api_bp.output(AttentionTileListResponse)
@api_bp.doc(summary="List the dashboard tiles for everything needing attention")
@admin_only
def list_attention_tiles(agency_id: int) -> AttentionTileListResponse:
    with get_session() as session:
        tiles = attention_tiles(session, agency_id)
    return AttentionTileListResponse([AttentionTileResponse.of(tile) for tile in tiles])


@api_bp.get(SETTINGS_ROUTE)
@api_bp.output(AdminSettingsResponse)
@api_bp.doc(summary="Read the agency's guest permissions and alert thresholds")
@admin_only
def read_admin_settings(agency_id: int) -> AdminSettingsResponse:
    with get_session() as session:
        return AdminSettingsResponse.of(_owned_agency(session, agency_id))


@api_bp.put(SETTINGS_ROUTE)
@api_bp.input(AdminSettingsRequest)
@api_bp.output(AdminSettingsResponse)
@api_bp.doc(summary="Save the agency's guest permissions, alert thresholds, and admin PIN")
@admin_only
def write_admin_settings(agency_id: int, json_data: AdminSettingsRequest) -> AdminSettingsResponse:
    with get_session() as session:
        agency = _owned_agency(session, agency_id)
        try:
            changed = save_admin_settings(session, agency, json_data.model_dump())
        except ValueError as error:
            logger.warning("Admin settings save rejected", extra={"agency_id": agency_id, "error": str(error)})
            raise HTTPError(HTTPStatus.UNPROCESSABLE_ENTITY, str(error)) from error
        session.commit()
        logger.info("Admin settings saved over the API", extra={"agency_id": agency_id, "changed": changed})
        return AdminSettingsResponse.of(agency)


@api_bp.get(PENDING_EXPIRATIONS_ROUTE)
@api_bp.output(PendingExpirationListResponse)
@api_bp.doc(summary="List the counted item/storage pairs still waiting on expiration dates")
@admin_only
def list_pending_expirations(agency_id: int) -> PendingExpirationListResponse:
    with get_session() as session:
        groups = pending_expiration_corrections(session, agency_id)
        session.commit()  # an empty list means the alerts those pairs raised were just reconciled
        return PendingExpirationListResponse([PendingExpirationGroupResponse.of(group) for group in sort_expiration_groups(groups)])


@api_bp.post(PENDING_EXPIRATIONS_ROUTE)
@api_bp.input(ExpirationCorrectionsRequest)
@api_bp.output(ExpirationCorrectionResultResponse)
@api_bp.doc(summary="Record the expiration dates every pending count actually carries")
@admin_only
def correct_pending_expirations(agency_id: int, json_data: ExpirationCorrectionsRequest) -> ExpirationCorrectionResultResponse:
    with get_session() as session:
        groups = pending_expiration_corrections(session, agency_id)
        if not groups:
            session.commit()
            raise HTTPError(HTTPStatus.NOT_FOUND, NOTHING_PENDING_MESSAGE)
        allocations_by_key = _allocations_by_key(groups, json_data)
        try:
            saved_count = save_expiration_corrections(session, agency_id, groups, allocations_by_key)
        except ValueError as error:
            session.rollback()
            logger.info("Expiration correction rejected", extra={"agency_id": agency_id, "error": str(error)})
            raise HTTPError(HTTPStatus.UNPROCESSABLE_ENTITY, str(error)) from error
        session.commit()
    logger.info(
        "Expiration counts corrected without inventory history",
        extra={"agency_id": agency_id, "item_storage_pair_count": saved_count},
    )
    return ExpirationCorrectionResultResponse(corrected_pair_count=saved_count)


def _allocations_by_key(
    groups: list[ExpirationEntryGroup],
    request_data: ExpirationCorrectionsRequest,
) -> dict[str, list[ExpirationAllocation]]:
    """Match each correction to its pending pair, refusing a save that leaves one unanswered."""
    by_pair = {(correction.item_id, correction.storage_id): correction for correction in request_data.corrections}
    allocations_by_key: dict[str, list[ExpirationAllocation]] = {}
    for group in groups:
        correction = by_pair.pop((group.spec.item_id, group.spec.storage_id), None)
        if correction is None:
            raise HTTPError(HTTPStatus.UNPROCESSABLE_ENTITY, UNANSWERED_PAIRS_MESSAGE)
        allocations = [entry.to_allocation() for entry in correction.allocations]
        try:
            validate_group_allocations(group, allocations)
        except ValueError as error:
            raise HTTPError(HTTPStatus.UNPROCESSABLE_ENTITY, str(error)) from error
        allocations_by_key[group.spec.key] = allocations
    if by_pair:
        raise HTTPError(HTTPStatus.UNPROCESSABLE_ENTITY, UNKNOWN_PAIR_MESSAGE)
    return allocations_by_key


def _owned_agency(session: Session, agency_id: int) -> Agency:
    agency = session.get(Agency, agency_id)
    if agency is None:
        logger.warning("Admin settings request rejected: unknown agency", extra={"agency_id": agency_id})
        raise HTTPError(HTTPStatus.NOT_FOUND, UNKNOWN_AGENCY_MESSAGE)
    return agency
