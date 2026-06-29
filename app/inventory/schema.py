"""Pydantic models for inventory inputs/outputs."""

from datetime import datetime

from pydantic import BaseModel, Field

from app.shared.validation_types import ItemName, OptionalParsedInt, OptionalPositiveInt, QuantityDelta, RequiredCountInput

from .constants import OperationType


class ScanStoragesRequest(BaseModel):
    """Scan storage-selection request payload."""

    item_id: int = Field(..., gt=0)
    from_location_id: OptionalParsedInt = None
    to_location_id: OptionalParsedInt = None
    same_location_error: str | None = None
    show_scan_route: bool = False


class AdminScanRouteRequest(BaseModel):
    """Admin scan route-selection payload."""

    from_location_id: OptionalParsedInt = None
    to_location_id: OptionalParsedInt = None
    same_location_error: str | None = None


class ScanItemRequest(BaseModel):
    """Scan item request payload."""

    item_id: int = Field(..., gt=0)
    from_location_id: OptionalParsedInt = None
    to_location_id: OptionalParsedInt = None
    counter_value: RequiredCountInput


class ItemResponse(BaseModel):
    """Item response payload."""

    id: int
    agency_id: int
    upc: str
    secondary_upcs: list[str] = Field(default_factory=list)
    active: bool
    guest_quick_adjust: bool
    tag_ids: list[int]
    increments: str | None
    name: ItemName
    image: str | None
    last_accessed: datetime | None
    min_quantity: OptionalPositiveInt
    max_quantity: OptionalPositiveInt
    batch_size: OptionalPositiveInt
    restock_delivery_days: OptionalPositiveInt
    prior_daily_usage: float | None


class ActionLogResponse(BaseModel):
    """Action log response payload."""

    id: int
    agency_id: int
    item_id: int | None
    operation_type: OperationType
    from_location_id: int | None
    to_location_id: int | None
    quantity_delta: QuantityDelta
    admin_action: bool
    time_scanned: datetime
