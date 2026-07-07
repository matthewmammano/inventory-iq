"""Template DTOs for admin inventory count pages."""

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.inventory.expiration_ui_service import ExpirationBreakdown, expiration_breakdowns_by_item
from app.inventory.location_operations import build_location_count_rows
from app.inventory.ui import get_inventory_level_class


@dataclass(frozen=True, slots=True)
class InventoryCountPageRow:
    item: Any
    storage_counts: dict[int, int]
    storage_classes: dict[int, str]
    total: int
    total_class: str
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
                storage_classes={storage.id: get_inventory_level_class(storage_counts[storage.id]) for storage in storages},
                total=total,
                total_class=get_inventory_level_class(total),
                expiration_breakdown=expiration_breakdowns.get(item.id),
            )
        )
    return InventoryCountPage(inventory_data=rows, storages=storages)
