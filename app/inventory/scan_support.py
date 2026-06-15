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
        return ScanPermissions(count=bool(row[0]), restock=bool(row[1])) if row else ScanPermissions(False, False)
    except Exception:
        logger.exception("Scan permissions lookup failed")
        return ScanPermissions(count=False, restock=False)


def storages_for_scan(agency_id: int, direction: str, is_admin: bool, session: Session) -> list[AgencyStorages]:
    if is_admin:
        return list_locations(agency_id, session=session)
    default_location_id = get_device_location_id(agency_id, session)
    access_filter = {"user_access_from": True} if direction == "from" else {"user_access_to": True}
    return list_locations(agency_id, agency_location_id=default_location_id, session=session, **access_filter)


def operation_from_storage_ids(
    from_storage_id: int | None,
    to_storage_id: int | None,
) -> tuple[OperationType, int | None, int | None]:
    if from_storage_id == VIRTUAL_LOCATION_RESTOCK:
        return OperationType.RESTOCK, None, to_storage_id
    if from_storage_id == VIRTUAL_LOCATION_COUNT:
        return OperationType.COUNT, None, to_storage_id
    if from_storage_id == to_storage_id:
        raise ValueError("Invalid operation parameters")
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
    *,
    is_admin: bool = False,
) -> str:
    from_storage = get_storage(from_storage_id, current_user.id) if from_storage_id else None
    to_storage = get_storage(to_storage_id, current_user.id) if to_storage_id else None
    from_name = _scan_storage_name(from_storage, is_admin)
    to_name = _scan_storage_name(to_storage, is_admin)

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


def _scan_storage_name(storage: AgencyStorages | None, is_admin: bool) -> str | None:
    if storage is None:
        return None
    return storage.full_name if is_admin else storage.name


def can_skip_storage_selection(
    from_storages: list[AgencyStorages],
    to_storages: list[AgencyStorages],
    permissions: ScanPermissions,
) -> bool:
    return _single_scan_pair(from_storages, to_storages, permissions) is not None


def redirect_to_scan_item(
    route: str,
    squad: str,
    item_id: int,
    from_storages: list[AgencyStorages],
    to_storages: list[AgencyStorages],
    permissions: ScanPermissions,
):
    from_id, to_id = _single_scan_pair(from_storages, to_storages, permissions) or (None, None)
    return redirect(
        url_for(
            f"{route}.scan_item",
            squad=squad,
            item_id=item_id,
            from_location_id=from_id,
            to_location_id=to_id,
            user_count_allow=permissions.count,
            user_restock_allow=permissions.restock,
        )
    )


def single_scan_from_id(
    from_storages: list[AgencyStorages],
    permissions: ScanPermissions,
) -> int | None:
    """Return the only available FROM choice, including virtual choices."""
    return _single_from_id(from_storages, permissions)


def single_scan_to_id(
    to_storages: list[AgencyStorages],
    from_storage_id: int | None = None,
) -> int | None:
    """Return the only available TO choice, including TAKE."""
    choices = _valid_to_ids(to_storages, from_storage_id)
    return choices[0] if len(choices) == 1 else None


def _single_from_id(
    from_storages: list[AgencyStorages],
    permissions: ScanPermissions,
) -> int | None:
    choices = [storage.id for storage in from_storages]
    if permissions.restock:
        choices.append(VIRTUAL_LOCATION_RESTOCK)
    if permissions.count:
        choices.append(VIRTUAL_LOCATION_COUNT)
    return choices[0] if len(choices) == 1 else None


def _single_to_id(to_storages: list[AgencyStorages]) -> int | None:
    choices = _valid_to_ids(to_storages, None)
    return choices[0] if len(choices) == 1 else None


def _single_scan_pair(
    from_storages: list[AgencyStorages],
    to_storages: list[AgencyStorages],
    permissions: ScanPermissions,
) -> tuple[int, int] | None:
    pairs = [
        (from_id, to_id) for from_id in _valid_from_ids(from_storages, to_storages, permissions) for to_id in _valid_to_ids(to_storages, from_id)
    ]
    return pairs[0] if len(pairs) == 1 else None


def _valid_from_ids(
    from_storages: list[AgencyStorages],
    to_storages: list[AgencyStorages],
    permissions: ScanPermissions,
) -> list[int]:
    choices = [storage.id for storage in from_storages]
    if permissions.restock and to_storages:
        choices.append(VIRTUAL_LOCATION_RESTOCK)
    if permissions.count and to_storages:
        choices.append(VIRTUAL_LOCATION_COUNT)
    return choices


def _valid_to_ids(to_storages: list[AgencyStorages], from_storage_id: int | None) -> list[int]:
    if from_storage_id in (VIRTUAL_LOCATION_RESTOCK, VIRTUAL_LOCATION_COUNT):
        return [storage.id for storage in to_storages]
    return [
        VIRTUAL_LOCATION_TAKEOUT,
        *(storage.id for storage in to_storages if storage.id != from_storage_id),
    ]


def scan_fallback_endpoint(route: str) -> str:
    return f"{route}.{'admin_scan_items' if route == 'admin' else 'index'}"
