"""Pydantic models for inventory inputs/outputs."""

from collections.abc import Mapping
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from typing import Annotated, Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, BeforeValidator, Field, ValidationInfo, field_validator, model_validator

from app.shared.validation_types import ItemName, OptionalParsedInt, OptionalPositiveInt, Quantity, RequiredCountInput
from app.shared.validators import validate_iso_date

from .constants import OperationType


def _blank_to_none(value: Any) -> Any:
    return None if isinstance(value, str) and not value.strip() else value


OptionalIsoDate = Annotated[date | None, BeforeValidator(_blank_to_none)]


class ScanStartQuery(BaseModel):
    """Scan start query parameters."""

    item_id: OptionalParsedInt = None
    upc: str | None = None


class ScanItemQuery(BaseModel):
    """Scan item query parameters."""

    item_id: OptionalParsedInt = None
    from_storage_id: OptionalParsedInt = None
    to_storage_id: OptionalParsedInt = None
    user_count_allow: bool = False
    user_restock_allow: bool = False
    show_scan_route: bool = False

    @classmethod
    def from_query(cls, values: Mapping[str, Any], *, is_admin: bool) -> "ScanItemQuery":
        return cls.model_validate(_query_values_with_permission_defaults(values, is_admin=is_admin))

    @model_validator(mode="after")
    def default_takeout_destination(self) -> "ScanItemQuery":
        if self.to_storage_id is None and not self.user_count_allow and not self.user_restock_allow:
            self.to_storage_id = -1
        return self


class HistoryDateRange(BaseModel):
    """History report date range with UTC bounds derived from agency-local dates."""

    timezone: str
    start_date: OptionalIsoDate = None
    end_date: OptionalIsoDate = None

    @field_validator("start_date", "end_date", mode="before")
    @classmethod
    def validate_date_text(cls, value: Any, info: ValidationInfo) -> Any:
        if value is None or value == "":
            return None
        if not isinstance(value, str):
            return value
        label = "Start date" if info.field_name == "start_date" else "End date"
        return validate_iso_date(value, label)

    @model_validator(mode="after")
    def validate_range(self) -> "HistoryDateRange":
        today = self.local_today
        if self.start_date and self.start_date > today:
            raise ValueError(f"Start date cannot be after {today.isoformat()}.")
        if self.end_date and self.end_date > today:
            raise ValueError(f"End date cannot be after {today.isoformat()}.")
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("Start date must be before end date.")
        return self

    @property
    def start_utc(self) -> datetime | None:
        return self._local_midnight_utc(self.start_date) if self.start_date else None

    @property
    def end_utc(self) -> datetime | None:
        return self._local_midnight_utc(self.end_date + timedelta(days=1)) if self.end_date else None

    @property
    def start_label(self) -> str:
        return self.start_date.isoformat() if self.start_date else ""

    @property
    def end_label(self) -> str:
        return self.end_date.isoformat() if self.end_date else ""

    @property
    def local_today(self) -> date:
        return datetime.now(self.local_timezone).date()

    @property
    def local_timezone(self) -> tzinfo:
        try:
            return ZoneInfo(self.timezone)
        except Exception:
            return UTC

    def _local_midnight_utc(self, day: date) -> datetime:
        return datetime.combine(day, time.min, tzinfo=self.local_timezone).astimezone(UTC).replace(tzinfo=None)


class HistoryPageQuery(BaseModel):
    """History list query parameters."""

    page: OptionalParsedInt = None

    @property
    def page_number(self) -> int:
        return max(self.page or 1, 1)


def _query_values_with_permission_defaults(values: Mapping[str, Any], *, is_admin: bool) -> dict[str, Any]:
    query_values = dict(values)
    for key in ("user_count_allow", "user_restock_allow"):
        value = str(query_values.get(key, "")).lower()
        query_values[key] = value != "false" if is_admin else value == "true"
    if "show_scan_route" in query_values:
        query_values["show_scan_route"] = query_values["show_scan_route"] == "1"
    return query_values


class ScanStoragesRequest(BaseModel):
    """Scan storage-selection request payload."""

    item_id: int = Field(..., gt=0)
    from_storage_id: OptionalParsedInt = None
    to_storage_id: OptionalParsedInt = None
    same_location_error: str | None = None
    show_scan_route: bool = False


class AdminScanRouteRequest(BaseModel):
    """Admin scan route-selection payload."""

    from_storage_id: OptionalParsedInt = None
    to_storage_id: OptionalParsedInt = None
    same_location_error: str | None = None


class ScanItemRequest(BaseModel):
    """Scan item request payload."""

    item_id: int = Field(..., gt=0)
    from_storage_id: OptionalParsedInt = None
    to_storage_id: OptionalParsedInt = None
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
    expiration_tracking_enabled: bool
    expiration_notice_days_override: OptionalPositiveInt
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
    from_storage_id: int | None
    to_storage_id: int | None
    quantity: Quantity
    admin_action: bool
    time_scanned: datetime
