"""Typed requests for admin UPC review actions."""

from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, field_validator, model_validator


class PendingUpcReviewAction(StrEnum):
    ADD = "ADD"
    RESOLVE = "RESOLVE"
    IGNORE = "IGNORE"
    UNIGNORE = "UNIGNORE"
    REMOVE = "REMOVE"


class PendingUpcReviewRequest(BaseModel):
    action: PendingUpcReviewAction
    unknown_upc_id: int | None = None
    item_id: int | None = None

    @field_validator("unknown_upc_id", "item_id", mode="before")
    @classmethod
    def _blank_id_to_none(cls, value: Any) -> Any:
        return None if value in (None, "") else value

    @model_validator(mode="after")
    def _validate_required_ids(self) -> Self:
        if self.action == PendingUpcReviewAction.ADD:
            return self
        if self.unknown_upc_id is None:
            raise ValueError("Pending UPC not found.")
        if self.action == PendingUpcReviewAction.RESOLVE and self.item_id is None:
            raise ValueError("Select an item.")
        return self
