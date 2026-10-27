"""Request models for the bulk edit endpoints."""

from collections.abc import Iterable, Sequence

from pydantic import BaseModel, Field, model_validator

from app.api.schema import LOCKED_INPUT, ExpirationAllocationRequest
from app.inventory.bulk_edit_service import BulkEditData
from app.inventory.bulk_location_service import bulk_expiration_key
from app.inventory.constants import OperationType
from app.inventory.expiration_service import ExpirationAllocation

DUPLICATE_CELL_MESSAGE = "Each item and storage pair may appear once per operation."


class BulkQuantityRequest(BaseModel):
    """One cell of the bulk grid: the quantity this item reaches in this storage, plus its dates when tracked."""

    model_config = LOCKED_INPUT

    item_id: int = Field(gt=0)
    storage_id: int = Field(gt=0)
    quantity: int = Field(ge=0)
    expiration_allocations: list[ExpirationAllocationRequest] = Field(default_factory=list)

    @property
    def cell(self) -> tuple[int, int]:
        return (self.item_id, self.storage_id)


class BulkEditRequest(BaseModel):
    """One bulk submission for a location: the counts and vendor restocks the admin entered in the grid."""

    model_config = LOCKED_INPUT

    counts: list[BulkQuantityRequest] = Field(default_factory=list)
    restocks: list[BulkQuantityRequest] = Field(default_factory=list)

    @model_validator(mode="after")
    def reject_repeated_cells(self) -> "BulkEditRequest":
        for entries in (self.counts, self.restocks):
            if len({entry.cell for entry in entries}) != len(entries):
                raise ValueError(DUPLICATE_CELL_MESSAGE)
        return self

    def to_bulk_edit_data(self) -> BulkEditData:
        return BulkEditData(
            counts=_quantities(self.counts),
            restocks=_quantities(self.restocks),
            expiration_allocations_by_key=self._allocations_by_key(),
        )

    def _allocations_by_key(self) -> dict[str, list[ExpirationAllocation]]:
        return {
            bulk_expiration_key(operation, entry.item_id, entry.storage_id): [
                allocation.to_allocation() for allocation in entry.expiration_allocations
            ]
            for operation, entries in self._entries_by_operation()
            for entry in entries
            if entry.expiration_allocations
        }

    def _entries_by_operation(self) -> Iterable[tuple[OperationType, Sequence[BulkQuantityRequest]]]:
        return ((OperationType.COUNT, self.counts), (OperationType.RESTOCK, self.restocks))


def _quantities(entries: Sequence[BulkQuantityRequest]) -> dict[tuple[int, int], int]:
    return {entry.cell: entry.quantity for entry in entries}
