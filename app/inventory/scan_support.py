"""Support helpers for inventory scan flows."""

from dataclasses import dataclass

from flask import redirect, url_for
from flask_login import current_user
from loguru import logger
from sqlalchemy.orm import Session

from app.auth.device_locations import get_device_location_id
from app.auth.models import AgencyStorages
from app.auth.queries import get_agency_permissions, get_storage, list_locations
from app.shared.validators import parse_optional_int

from .constants import (
    VIRTUAL_LOCATION_COUNT,
    VIRTUAL_LOCATION_RESTOCK,
    VIRTUAL_LOCATION_TAKEOUT,
    OperationType,
)


@dataclass
class ScanPermissions:
    count: bool
    restock: bool


def get_scan_permissions(squad: str, *, is_admin: bool = False) -> ScanPermissions:
    if is_admin:
        return ScanPermissions(count=True, restock=True)
    try:
        row = get_agency_permissions(squad)
        return (
            ScanPermissions(count=bool(row[0]), restock=bool(row[1]))
            if row
            else ScanPermissions(False, False)
        )
    except Exception:
        logger.exception("Error fetching scan permissions")
        return ScanPermissions(count=False, restock=False)


def storages_for_scan(
    agency_id: int, direction: str, is_admin: bool, session: Session
) -> list[AgencyStorages]:
    if is_admin:
        return list_locations(agency_id, session=session)
    default_location_id = get_device_location_id(agency_id, session)
    access_filter = {"user_access_from": True} if direction == "from" else {"user_access_to": True}
    return list_locations(
        agency_id, agency_location_id=default_location_id, session=session, **access_filter
    )


def operation_from_storage_ids(
    from_storage_id: int | None,
    to_storage_id: int | None,
) -> tuple[OperationType, int | None, int | None]:
    if from_storage_id == VIRTUAL_LOCATION_RESTOCK:
        return OperationType.RESTOCK, None, to_storage_id
    if from_storage_id == VIRTUAL_LOCATION_COUNT:
        return OperationType.COUNT, None, to_storage_id
    if from_storage_id and from_storage_id > 0 and to_storage_id and to_storage_id > 0:
        return OperationType.TRANSFER, from_storage_id, to_storage_id
    if from_storage_id and from_storage_id > 0 and to_storage_id == VIRTUAL_LOCATION_TAKEOUT:
        return OperationType.TAKEOUT, from_storage_id, None
    raise ValueError("Invalid operation parameters")


def resolve_scan_location(storage_id, agency_id: int, *, takeout_allowed: bool = False):
    parsed_id = parse_optional_int(storage_id)
    if parsed_id in (VIRTUAL_LOCATION_RESTOCK, VIRTUAL_LOCATION_COUNT):
        return parsed_id
    if takeout_allowed and parsed_id == VIRTUAL_LOCATION_TAKEOUT:
        return VIRTUAL_LOCATION_TAKEOUT
    return get_storage(parsed_id, agency_id) if parsed_id is not None else None


def scan_success_message(
    operation_type: OperationType,
    item_name: str,
    quantity: int,
    from_storage_id: int | None,
    to_storage_id: int | None,
) -> str:
    from_storage = get_storage(from_storage_id, current_user.id) if from_storage_id else None
    to_storage = get_storage(to_storage_id, current_user.id) if to_storage_id else None
    from_name = from_storage.full_name if from_storage else None
    to_name = to_storage.full_name if to_storage else None

    match operation_type:
        case OperationType.COUNT:
            return f"Set {item_name} quantity to {quantity} at {to_name}."
        case OperationType.RESTOCK:
            return f"Restocked {quantity} {item_name} to {to_name}."
        case OperationType.TAKEOUT:
            return f"Removed {quantity} {item_name} from {from_name}."
        case OperationType.TRANSFER:
            return f"Transferred {quantity} {item_name} from {from_name} to {to_name}."
    return f"Operation completed for {item_name}."


def can_skip_storage_selection(
    from_storages: list[AgencyStorages],
    to_storages: list[AgencyStorages],
    permissions: ScanPermissions,
) -> bool:
    from_count = len(from_storages) + int(permissions.count) + int(permissions.restock)
    to_count = len(to_storages) + 1
    return from_count == to_count == 1


def redirect_to_scan_item(
    route: str,
    squad: str,
    item_id: int,
    from_storages: list[AgencyStorages],
    to_storages: list[AgencyStorages],
    permissions: ScanPermissions,
):
    return redirect(
        url_for(
            f"{route}.scan_item",
            squad=squad,
            item_id=item_id,
            from_location_id=from_storages[0].id if from_storages else None,
            to_location_id=to_storages[0].id if to_storages else None,
            user_count_allow=permissions.count,
            user_restock_allow=permissions.restock,
        )
    )


def scan_fallback_endpoint(route: str) -> str:
    return f"{route}.{'admin_scan_items' if route == 'admin' else 'index'}"
