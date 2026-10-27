"""Request models for the admin overview surface."""

from pydantic import BaseModel, Field, model_validator

from app.api.schema import LOCKED_INPUT, ExpirationAllocationRequest
from app.inventory.admin_edit_schema import AdminSettingsForm
from app.inventory.expiration_ui_service import validate_expiration_date


class AdminSettingsRequest(AdminSettingsForm):
    """Every admin setting at once; `pin` is set only when it is being changed."""

    model_config = LOCKED_INPUT


class ExpirationCorrectionRequest(BaseModel):
    """The dates one item/storage pair's counted stock actually carries."""

    model_config = LOCKED_INPUT

    item_id: int = Field(gt=0)
    storage_id: int = Field(gt=0)
    allocations: list[ExpirationAllocationRequest] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_dates(self) -> "ExpirationCorrectionRequest":
        for allocation in self.allocations:
            if allocation.expires_on is not None:
                validate_expiration_date(allocation.expires_on)
        return self


class ExpirationCorrectionsRequest(BaseModel):
    """One correction per pair still waiting on dates; every pending pair has to be answered."""

    model_config = LOCKED_INPUT

    corrections: list[ExpirationCorrectionRequest] = Field(min_length=1)
