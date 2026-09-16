"""Business service for saving one scan submission."""

from dataclasses import dataclass

from app.auth.models import Storage

from .constants import OperationType
from .expiration_service import ExpirationAllocation
from .item_queries import get_agency_item
from .models import ActionLog, Item
from .mutation_service import MutationTarget, inventory_operation
from .quantity_service import has_item_count
from .scan_support import (
    ScanActor,
    ScanPermissions,
    operation_from_storage_ids,
    resolve_scan_location,
    validate_scan_route,
)
from .schema import ScanItemRequest


class ScanSubmitItemNotFoundError(LookupError):
    """Raised when a scan submit references an item outside the agency."""


class ScanSubmitRouteError(ValueError):
    """Raised when the selected scan route is not allowed."""


@dataclass(frozen=True, slots=True)
class ScanSubmitResult:
    action: ActionLog
    item: Item
    operation_type: OperationType
    quantity: int
    from_storage_id: int | None
    to_storage_id: int | None
    from_storage: Storage | int | None
    to_storage: Storage | int | None
    initial_count_required: bool


def save_scan_submission(
    actor: ScanActor,
    *,
    request_data: ScanItemRequest,
    permissions: ScanPermissions,
    expiration_allocations: list[ExpirationAllocation] | None = None,
) -> ScanSubmitResult:
    """Validate and persist one scan submission."""
    session, agency_id, is_admin = actor.session, actor.agency_id, actor.is_admin
    route_error = validate_scan_route(actor, request_data.from_storage_id, request_data.to_storage_id, permissions)
    if route_error:
        raise ScanSubmitRouteError(route_error)

    item = get_agency_item(agency_id, request_data.item_id, session=session)
    if not item:
        raise ScanSubmitItemNotFoundError

    from_storage = resolve_scan_location(request_data.from_storage_id, agency_id, session=session)
    to_storage = resolve_scan_location(request_data.to_storage_id, agency_id, takeout_allowed=True, session=session)
    operation_type, from_storage_id, to_storage_id = operation_from_storage_ids(
        request_data.from_storage_id,
        request_data.to_storage_id,
    )
    target = MutationTarget(
        agency_id=agency_id,
        item_id=item.id,
        quantity=request_data.counter_value,
        operation_type=operation_type,
        from_storage=from_storage_id,
        to_storage=to_storage_id,
    )
    action = inventory_operation(target, admin_action=is_admin, expiration_allocations=expiration_allocations, session=session)
    initial_count_required = not operation_type.is_count and not has_item_count(session, agency_id, item.id)
    session.commit()
    return ScanSubmitResult(
        action=action,
        item=item,
        operation_type=operation_type,
        quantity=request_data.counter_value,
        from_storage_id=from_storage_id,
        to_storage_id=to_storage_id,
        from_storage=from_storage,
        to_storage=to_storage,
        initial_count_required=initial_count_required,
    )
