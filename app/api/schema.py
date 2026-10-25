"""Request and query models for the JSON API."""

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from app.inventory.expiration_service import ExpirationAllocation
from app.inventory.schema import ScanItemRequest

LOCKED_INPUT = ConfigDict(extra="forbid", str_strip_whitespace=True)


class StorageOptionsQuery(BaseModel):
    """Narrow the storage choices to one location; omitted means the device's own default."""

    model_config = LOCKED_INPUT

    location_id: int | None = Field(default=None, gt=0)


class UpcLookupQuery(BaseModel):
    """A scanned code as the gun sent it; an unknown or malformed one is a miss, not a bad request."""

    model_config = LOCKED_INPUT

    upc: str = Field(min_length=1, max_length=64)


class ExpirationAllocationRequest(BaseModel):
    """How many units of one scan belong to one expiration date."""

    model_config = LOCKED_INPUT

    expires_on: date | None = None
    quantity: int = Field(ge=0)

    def to_allocation(self) -> ExpirationAllocation:
        return ExpirationAllocation(expires_on=self.expires_on, quantity=self.quantity)


class ScanRequest(ScanItemRequest):
    """One scan the kiosk is submitting, with its expiration split when the item is tracked."""

    model_config = LOCKED_INPUT

    expiration_allocations: list[ExpirationAllocationRequest] = Field(default_factory=list)

    def allocations(self) -> list[ExpirationAllocation] | None:
        return [entry.to_allocation() for entry in self.expiration_allocations] or None
