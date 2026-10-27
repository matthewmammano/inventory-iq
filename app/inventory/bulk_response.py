"""Response models for bulk edit: the grid, what a submission wrote, and what it still needs dated."""

from collections.abc import Sequence

from pydantic import BaseModel, computed_field

from app.auth.models import Storage
from app.auth.response import StorageResponse

from .bulk_edit_service import BulkEditSaveResult
from .bulk_location_service import LocationQuantityGrid
from .constants import OperationType
from .expiration_ui_service import ExpirationEntryGroup
from .models import Item
from .response import ExpirationEntryResponse


class BulkEditCellResponse(BaseModel):
    """One item's quantity in one storage, and whether its count is too old to restock against."""

    storage_id: int
    quantity: int
    count_required: bool


class BulkEditRowResponse(BaseModel):
    """One item's row of the grid."""

    item_id: int
    item_name: str
    expiration_tracking: bool
    suggested_restock: bool
    cells: list[BulkEditCellResponse]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def stale(self) -> bool:
        return any(cell.count_required for cell in self.cells)


class BulkEditGridResponse(BaseModel):
    """Every active item against every storage of one location, as the grid screen reads it."""

    location_id: int
    location_name: str
    stale_count_days: int
    storages: list[StorageResponse]
    rows: list[BulkEditRowResponse]

    @classmethod
    def of(
        cls,
        grid: LocationQuantityGrid,
        *,
        required: dict[int, set[int]],
        suggested_restock_item_ids: set[int],
        stale_count_days: int,
    ) -> "BulkEditGridResponse":
        return cls(
            location_id=grid.location.id,
            location_name=grid.location.name,
            stale_count_days=stale_count_days,
            storages=[StorageResponse.of(storage) for storage in grid.storages],
            rows=[_row(item, grid, required, suggested_restock_item_ids) for item in grid.items],
        )


class BulkEditSaveResponse(BaseModel):
    """What one saved bulk submission wrote. The caller phrases its own confirmation from these counts."""

    location_id: int
    count_entry_count: int
    restock_entry_count: int

    @computed_field  # type: ignore[prop-decorator]
    @property
    def entry_count(self) -> int:
        return self.count_entry_count + self.restock_entry_count

    @classmethod
    def of(cls, result: BulkEditSaveResult, agency_location_id: int) -> "BulkEditSaveResponse":
        return cls(
            location_id=agency_location_id,
            count_entry_count=result.count_entry_count,
            restock_entry_count=result.restock_entry_count,
        )


class BulkDatingGroupResponse(BaseModel):
    """One cell of a bulk submission that cannot save until its units are split across expiration dates."""

    item_id: int
    storage_id: int
    operation: OperationType
    entry: ExpirationEntryResponse

    @classmethod
    def of(cls, group: ExpirationEntryGroup) -> "BulkDatingGroupResponse":
        return cls(
            item_id=group.spec.item_id,
            storage_id=group.spec.storage_id,
            operation=group.spec.operation_type,
            entry=ExpirationEntryResponse.of(group),
        )


class BulkDatingRequiredResponse(BaseModel):
    """The answer to a submission held back for dates: what to collect, so the client can resubmit the same draft."""

    needs_dating: list[BulkDatingGroupResponse]

    @classmethod
    def of(cls, groups: Sequence[ExpirationEntryGroup]) -> "BulkDatingRequiredResponse":
        return cls(needs_dating=[BulkDatingGroupResponse.of(group) for group in groups])


def _row(
    item: Item,
    grid: LocationQuantityGrid,
    required: dict[int, set[int]],
    suggested_restock_item_ids: set[int],
) -> BulkEditRowResponse:
    return BulkEditRowResponse(
        item_id=item.id,
        item_name=item.name,
        expiration_tracking=bool(item.expiration_tracking_enabled),
        suggested_restock=item.id in suggested_restock_item_ids,
        cells=[_cell(item, storage, grid, required) for storage in grid.storages],
    )


def _cell(item: Item, storage: Storage, grid: LocationQuantityGrid, required: dict[int, set[int]]) -> BulkEditCellResponse:
    return BulkEditCellResponse(
        storage_id=storage.id,
        quantity=grid.quantities.get((item.id, storage.id), 0),
        count_required=storage.id in required.get(item.id, set()),
    )
