"""Pydantic models for inventory inputs/outputs."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.shared.validators import (
    parse_optional_int,
    validate_non_negative_integer,
    validate_positive_integer,
    validate_string_length,
)

from .constants import OperationType


class ScanStoragesRequest(BaseModel):
    """Scan storage-selection request payload."""

    item_id: int = Field(..., gt=0)
    from_location_id: int | None = None
    to_location_id: int | None = None
    same_location_error: str | None = None

    @field_validator("from_location_id", "to_location_id", mode="before")
    @classmethod
    def parse_location_id(cls, value: int | str | None) -> int | None:
        return parse_optional_int(value)


class ScanItemRequest(BaseModel):
    """Scan item request payload."""

    item_id: int = Field(..., gt=0)
    from_location_id: int | None = None
    to_location_id: int | None = None
    counter_value: int = Field(..., gt=0)

    @field_validator("from_location_id", "to_location_id", mode="before")
    @classmethod
    def parse_location_id(cls, value: int | str | None) -> int | None:
        return parse_optional_int(value)

    @field_validator("counter_value", mode="before")
    @classmethod
    def parse_counter_value(cls, value: int | str | None) -> int:
        if value is None or value == "":
            raise ValueError("Quantity is required")
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
        raise ValueError("Quantity must be a valid number")


class ItemResponse(BaseModel):
    """Item response payload."""

    id: int
    agency_id: int
    upc: str | None
    active: bool
    tag_ids: list[int]
    increments: str | None
    name: str
    image: str | None
    last_accessed: datetime | None
    min_quantity: int | None
    max_quantity: int | None
    batch_size: int | None
    restock_delivery_days: int | None
    prior_daily_usage: float | None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return validate_string_length(value, "name", 100, allow_none=False, allow_empty=False) or ""

    @field_validator("min_quantity", "max_quantity", "batch_size", "restock_delivery_days")
    @classmethod
    def validate_positive_ints(cls, value: int | None, info) -> int | None:
        return validate_positive_integer(value, info.field_name or "value", allow_none=True)

    @field_validator("tag_ids")
    @classmethod
    def validate_tag_ids(cls, value: list[int]) -> list[int]:
        if not isinstance(value, list):
            raise ValueError("tag_ids must be a list")
        return value


class ActionLogResponse(BaseModel):
    """Action log response payload."""

    id: int
    agency_id: int
    item_id: int | None
    operation_type: OperationType
    from_location_id: int | None
    to_location_id: int | None
    quantity_delta: int
    admin_action: bool
    time_scanned: datetime

    @field_validator("quantity_delta")
    @classmethod
    def validate_quantity(cls, value: int | None) -> int | None:
        return validate_non_negative_integer(value, "quantity_delta", allow_none=False)
