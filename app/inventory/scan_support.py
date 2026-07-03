"""Support helpers for inventory scan flows."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from flask import redirect, url_for
from flask_login import current_user
from loguru import logger
from markupsafe import Markup
from sqlalchemy.orm import Session

from app.auth.device_locations import get_device_location_id
from app.auth.models import AgencyStorages
from app.auth.queries import get_agency_permissions, get_storage, list_locations
from app.shared.html_formatting import bold_item_name
from app.shared.validators import parse_optional_int

from .constants import (
    VIRTUAL_LOCATION_COUNT,
    VIRTUAL_LOCATION_RESTOCK,
    VIRTUAL_LOCATION_TAKEOUT,
    OperationType,
)


class ScanSurface(StrEnum):
    ADMIN = "admin"
    GUEST = "guest"

    @classmethod
    def from_admin_flag(cls, is_admin: bool) -> "ScanSurface":
        return cls.ADMIN if is_admin else cls.GUEST

    def endpoint(self, endpoint_name: str) -> str:
        return f"{self.value}.{endpoint_name}"

    def fallback_url(self, squad: str) -> str:
        if self == ScanSurface.ADMIN:
            return url_for("admin.admin_scan_items", squad=squad)
        return url_for("guest.index", squad=squad)

    def scan_item_error_url(self, squad: str) -> str:
        if self == ScanSurface.ADMIN:
            return url_for("admin.admin_panel", squad=squad)
        return url_for("guest.index", squad=squad)

    def scan_item_cancel_url(self, squad: str, from_location_id: Any, to_location_id: Any) -> str:
        if self == ScanSurface.ADMIN:
            return self.admin_scan_items_url(squad, from_location_id=from_location_id, to_location_id=to_location_id)
        return url_for("guest.index", squad=squad)

    def admin_scan_items_url(
        self,
        squad: str,
        *,
        from_location_id: Any,
        to_location_id: Any,
        scan_error: str | None = None,
    ) -> str:
        return url_for(
            "admin.admin_scan_items",
            squad=squad,
            from_location_id=from_location_id,
            to_location_id=to_location_id,
            scan_error=scan_error,
        )


@dataclass(frozen=True, slots=True)
class ScanPermissions:
    count: bool
    restock: bool


@dataclass(frozen=True, slots=True)
class ScanStorageChoices:
    from_storages: list[AgencyStorages]
    to_storages: list[AgencyStorages]
    default_location_id: int | None


def get_scan_permissions(squad: str, *, is_admin: bool = False) -> ScanPermissions:
    if is_admin:
        return ScanPermissions(count=True, restock=True)
    try:
        row = get_agency_permissions(squad)
        return ScanPermissions(count=row.count, restock=row.restock) if row else ScanPermissions(False, False)
    except Exception:
        logger.exception("Scan permissions lookup failed", extra={"squad": squad, "admin": is_admin})
        return ScanPermissions(count=False, restock=False)


def load_scan_storage_choices(agency_id: int, is_admin: bool, session: Session) -> ScanStorageChoices:
    if is_admin:
        storages = list_locations(agency_id, session=session)
        return ScanStorageChoices(storages, storages, None)

    default_location_id = get_device_location_id(agency_id, session)
    storages = list_locations(agency_id, agency_location_id=default_location_id, session=session)
    return ScanStorageChoices(
        [storage for storage in storages if storage.user_access_from],
        [storage for storage in storages if storage.user_access_to],
        default_location_id,
    )


def storages_for_scan(agency_id: int, direction: str, is_admin: bool, session: Session) -> list[AgencyStorages]:
    choices = load_scan_storage_choices(agency_id, is_admin, session)
    return choices.from_storages if direction == "from" else choices.to_storages


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


def resolve_scan_location(
    storage_id: Any,
    agency_id: int,
    *,
    takeout_allowed: bool = False,
    session: Session | None = None,
):
    parsed_id = parse_optional_int(storage_id)
    if parsed_id in (VIRTUAL_LOCATION_RESTOCK, VIRTUAL_LOCATION_COUNT):
        return parsed_id
    if takeout_allowed and parsed_id == VIRTUAL_LOCATION_TAKEOUT:
        return VIRTUAL_LOCATION_TAKEOUT
    return get_storage(parsed_id, agency_id, session) if parsed_id is not None else None


def validate_scan_route(
    agency_id: int,
    from_storage_id: int | None,
    to_storage_id: int | None,
    permissions: ScanPermissions,
    *,
    is_admin: bool,
    session: Session,
) -> str | None:
    if from_storage_id is None or to_storage_id is None:
        return "Invalid storage combination."

    if from_storage_id == VIRTUAL_LOCATION_RESTOCK and not permissions.restock:
        return "RESTOCK is not allowed for this scan."
    if from_storage_id == VIRTUAL_LOCATION_COUNT and not permissions.count:
        return "COUNT is not allowed for this scan."

    choices = load_scan_storage_choices(agency_id, is_admin, session)
    from_storages = choices.from_storages
    to_storages = choices.to_storages
    valid_from_ids = set(_valid_from_ids(from_storages, to_storages, permissions))
    if from_storage_id not in valid_from_ids:
        return "Selected source storage is not available for this scan."

    valid_to_ids = set(_valid_to_ids(to_storages, from_storage_id))
    if to_storage_id not in valid_to_ids:
        return "Selected destination storage is not available for this scan."
    return None


def is_scan_route_allowed(
    agency_id: int,
    from_storage_id: int | None,
    to_storage_id: int | None,
    permissions: ScanPermissions,
    *,
    is_admin: bool,
    session: Session,
) -> bool:
    return (
        validate_scan_route(
            agency_id,
            from_storage_id,
            to_storage_id,
            permissions,
            is_admin=is_admin,
            session=session,
        )
        is None
    )


def format_scan_route_label(from_location, to_location, *, is_admin: bool) -> str:
    from_label = format_scan_location_label(from_location, is_admin=is_admin)
    to_label = format_scan_location_label(to_location, is_admin=is_admin, takeout_allowed=True)
    return f"{from_label} -> {to_label}"


def storage_selection_subtitle(item_name: str) -> Markup:
    return Markup("Choose FROM and TO for {item_name}").format(item_name=bold_item_name(item_name))


def format_scan_location_label(location, *, is_admin: bool, takeout_allowed: bool = False) -> str:
    if location == VIRTUAL_LOCATION_RESTOCK:
        return "RESTOCK"
    if location == VIRTUAL_LOCATION_COUNT:
        return "COUNT"
    if takeout_allowed and location == VIRTUAL_LOCATION_TAKEOUT:
        return "TAKE"
    if not isinstance(location, AgencyStorages):
        return "Unknown"
    return _scan_route_storage_name(location, is_admin)


def scan_success_message(
    operation_type: OperationType,
    item_name: str,
    quantity: int,
    from_storage_id: int | None,
    to_storage_id: int | None,
    *,
    is_admin: bool = False,
    from_storage: AgencyStorages | None = None,
    to_storage: AgencyStorages | None = None,
) -> Markup:
    if from_storage is None and from_storage_id:
        from_storage = get_storage(from_storage_id, current_user.id)
    if to_storage is None and to_storage_id:
        to_storage = get_storage(to_storage_id, current_user.id)
    from_name = _scan_storage_name(from_storage, is_admin)
    to_name = _scan_storage_name(to_storage, is_admin)

    match operation_type:
        case OperationType.COUNT:
            return Markup("Set {item_name} quantity to {quantity} at {to_name}.").format(
                item_name=bold_item_name(item_name),
                quantity=quantity,
                to_name=to_name,
            )
        case OperationType.RESTOCK:
            return Markup("Restocked {quantity} {item_name} to {to_name}.").format(
                quantity=quantity,
                item_name=bold_item_name(item_name),
                to_name=to_name,
            )
        case OperationType.TAKEOUT:
            return Markup("Removed {quantity} {item_name} from {from_name}.").format(
                quantity=quantity,
                item_name=bold_item_name(item_name),
                from_name=from_name,
            )
        case OperationType.TRANSFER:
            return Markup("Transferred {quantity} {item_name} from {from_name} to {to_name}.").format(
                quantity=quantity,
                item_name=bold_item_name(item_name),
                from_name=from_name,
                to_name=to_name,
            )
    return Markup("Operation completed for {item_name}.").format(item_name=bold_item_name(item_name))


def _scan_storage_name(storage: AgencyStorages | None, is_admin: bool) -> str | None:
    if storage is None:
        return None
    return storage.full_name if is_admin else storage.name


def _scan_route_storage_name(storage: AgencyStorages, is_admin: bool) -> str:
    location_name = storage.location.name if storage.location else ""
    if not location_name:
        return storage.name
    if is_admin:
        return f"{storage.name} ({location_name})"
    return f"{location_name}: {storage.name}"


def can_skip_storage_selection(
    from_storages: list[AgencyStorages],
    to_storages: list[AgencyStorages],
    permissions: ScanPermissions,
) -> bool:
    return _single_scan_pair(from_storages, to_storages, permissions) is not None


def redirect_to_scan_item(
    surface: ScanSurface,
    squad: str,
    item_id: int,
    from_storages: list[AgencyStorages],
    to_storages: list[AgencyStorages],
    permissions: ScanPermissions,
):
    from_id, to_id = _single_scan_pair(from_storages, to_storages, permissions) or (None, None)
    return redirect(
        url_for(
            surface.endpoint("scan_item"),
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
