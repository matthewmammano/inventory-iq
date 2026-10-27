"""Which location an admin report is about, and the DTOs for the inventory count page."""

from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy.orm import Session

from app.auth.models import Location
from app.inventory.expiration_ui_service import ExpirationBreakdown, expiration_breakdowns_by_item
from app.inventory.location_operations import build_location_count_rows

ALL_LOCATIONS_ID: Final[int] = 0


def select_report_location(locations: list[Location], requested_id: int | None, *, device_location_id: int | None) -> Location | None:
    """Falls back to the location this device is set to in settings, so a kiosk opens on its own squad."""
    if not locations:
        return None
    wanted_id = requested_id if requested_id is not None else device_location_id
    return next((location for location in locations if location.id == wanted_id), locations[0])


def select_history_location(locations: list[Location], requested_id: int | None, *, device_location_id: int | None) -> Location | None:
    """History spans every squad unless a tab or this device's setting names one."""
    if requested_id == ALL_LOCATIONS_ID:
        return None
    wanted_id = requested_id or device_location_id
    return next((location for location in locations if location.id == wanted_id), None)


@dataclass(frozen=True, slots=True)
class InventoryCountPageRow:
    item: Any
    storage_counts: dict[int, int]
    total: int
    expiration_breakdown: ExpirationBreakdown | None


@dataclass(frozen=True, slots=True)
class InventoryCountPage:
    inventory_data: list[InventoryCountPageRow]
    storages: list[Any]


def build_inventory_count_page(session: Session, agency_id: int, agency_location_id: int) -> InventoryCountPage:
    items, storages, counts = build_location_count_rows(session, agency_id, agency_location_id)
    expiration_breakdowns = expiration_breakdowns_by_item(session, agency_id, agency_location_id)
    rows = []
    for item in items:
        storage_counts = {storage.id: counts.get((item.id, storage.id), 0) for storage in storages}
        total = sum(storage_counts.values())
        rows.append(
            InventoryCountPageRow(
                item=item,
                storage_counts=storage_counts,
                total=total,
                expiration_breakdown=expiration_breakdowns.get(item.id),
            )
        )
    return InventoryCountPage(inventory_data=rows, storages=storages)
