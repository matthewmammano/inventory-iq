"""Request and query models for the JSON API."""

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from app.inventory.expiration_service import ExpirationAllocation
from app.inventory.schema import ScanItemRequest
from app.shared.validation_types import AdminPin, EmailAddress128

LOCKED_INPUT = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SignInRequest(BaseModel):
    """The account email and password someone is signing in with."""

    model_config = LOCKED_INPUT

    email: EmailAddress128
    password: str = Field(min_length=1)


class AdminPinRequest(BaseModel):
    """The 4-digit PIN someone is unlocking admin with; a PIN of any other length can never be right."""

    model_config = LOCKED_INPUT

    pin: AdminPin


class StorageOptionsQuery(BaseModel):
    """Narrow the storage choices to one location; omitted means the device's own default."""

    model_config = LOCKED_INPUT

    location_id: int | None = Field(default=None, gt=0)


class UpcLookupQuery(BaseModel):
    """A scanned code as the gun sent it; an unknown or malformed one is a miss, not a bad request."""

    model_config = LOCKED_INPUT

    upc: str = Field(min_length=1, max_length=64)


class DeviceLocationRequest(BaseModel):
    """The location a kiosk is being bound to, saved for a year against its device cookie."""

    model_config = LOCKED_INPUT

    location_id: int = Field(gt=0)


class ScanRouteQuery(BaseModel):
    """The from/to pair a scan screen was reached with; virtual ids are negative."""

    model_config = LOCKED_INPUT

    from_storage_id: int
    to_storage_id: int


class ExpirationOptionsQuery(ScanRouteQuery):
    """A scan route plus the quantity being saved, which sets how many units need dating."""

    quantity: int = Field(gt=0)


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
