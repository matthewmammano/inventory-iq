"""Business service for bulk inventory edits."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from sqlalchemy.orm import Session

from .bulk_forms import missing_required_count_cells
from .bulk_location_service import (
    LocationQuantityGrid,
    required_count_storage_ids,
    save_bulk_location_count,
    save_bulk_location_restock,
)
from .expiration_service import ExpirationAllocation, sync_expiration_alerts_after_save
from .expiration_ui_service import (
    ExpirationEntryGroup,
    build_expiration_entry_groups,
    bulk_expiration_specs,
    sort_expiration_groups,
)

UNKNOWN_CELL_MESSAGE: Final[str] = "Those items are not editable at this location."
REQUIRED_COUNT_MESSAGE: Final[str] = "Count these items at this location before restocking them."
EMPTY_SUBMISSION_MESSAGE: Final[str] = "No count or restock entries entered."


class BulkEditEmptyError(ValueError):
    """Raised when a bulk edit contains no count or restock entries."""


class BulkEditUnknownCellError(ValueError):
    """Raised when a submitted item or storage is not part of this location's grid."""


class BulkEditRequiredCountError(ValueError):
    """Raised when a storage whose count has gone stale is restocked without being counted first."""


@dataclass(frozen=True, slots=True)
class BulkEditSaveResult:
    count_entry_count: int
    restock_entry_count: int

    @property
    def total_entry_count(self) -> int:
        return self.count_entry_count + self.restock_entry_count


@dataclass(frozen=True, slots=True)
class BulkEditData:
    """What to save: the submitted counts/restocks and any expiration dates entered for them."""

    counts: dict[tuple[int, int], int]
    restocks: dict[tuple[int, int], int]
    expiration_allocations_by_key: dict[str, list[ExpirationAllocation]] | None = None

    @property
    def item_ids(self) -> set[int]:
        return {item_id for item_id, _ in (*self.counts, *self.restocks)}

    @property
    def allocations(self) -> dict[str, list[ExpirationAllocation]]:
        return self.expiration_allocations_by_key or {}


def validate_bulk_edit(session: Session, *, agency_id: int, grid: LocationQuantityGrid, data: BulkEditData) -> None:
    """Every submitted cell must belong to this grid, and a stale storage must be counted before it is restocked."""
    _reject_cells_outside_grid(grid, data)
    items = [item for item in grid.items if item.id in data.item_ids]
    required = required_count_storage_ids(session, agency_id, grid.location.id, items)
    if missing_required_count_cells(required, data.counts, data.restocks):
        raise BulkEditRequiredCountError(REQUIRED_COUNT_MESSAGE)


def bulk_dating_groups(session: Session, agency_id: int, data: BulkEditData) -> list[ExpirationEntryGroup]:
    """The tracked item/storage pairs this submission has to supply expiration dates for, in display order."""
    specs = bulk_expiration_specs(counts=data.counts, restocks=data.restocks)
    return sort_expiration_groups(build_expiration_entry_groups(session, agency_id, specs))


def groups_still_needing_dates(groups: Sequence[ExpirationEntryGroup], data: BulkEditData) -> list[ExpirationEntryGroup]:
    return [group for group in groups if not data.allocations.get(group.spec.key)]


def save_bulk_edit(session: Session, *, agency_id: int, agency_location_id: int, data: BulkEditData) -> BulkEditSaveResult:
    if not data.counts and not any(quantity > 0 for quantity in data.restocks.values()):
        raise BulkEditEmptyError(EMPTY_SUBMISSION_MESSAGE)

    allocations = data.allocations
    count_logs = save_bulk_location_count(session, agency_id, agency_location_id, data.counts, allocations) if data.counts else 0
    restock_logs = save_bulk_location_restock(session, agency_id, agency_location_id, data.restocks, allocations) if data.restocks else 0
    sync_expiration_alerts_after_save(session, agency_id, any(allocations.values()))
    session.commit()
    return BulkEditSaveResult(count_logs, restock_logs)


def _reject_cells_outside_grid(grid: LocationQuantityGrid, data: BulkEditData) -> None:
    item_ids = {item.id for item in grid.items}
    storage_ids = {storage.id for storage in grid.storages}
    for item_id, storage_id in (*data.counts, *data.restocks):
        if item_id not in item_ids or storage_id not in storage_ids:
            raise BulkEditUnknownCellError(UNKNOWN_CELL_MESSAGE)
