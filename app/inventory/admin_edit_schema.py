"""Pydantic schemas for admin edit forms."""

from pydantic import BaseModel, Field, model_validator

from app.auth.notification_preferences import NOTIFICATION_PREFERENCES, AlertEmailFrequency, ScanAlertScope
from app.inventory.constants import UPC_GENERATION_PREFIX
from app.inventory.models import validate_upc_code
from app.shared.validation_types import (
    AdminPinChange,
    EmailAddress128,
    ImageSource,
    Increments,
    ItemName,
    OptionalPositiveInt,
    PositiveInt,
    QuietTime,
    TagColor,
    TagName,
)


class AdminItemForm(BaseModel):
    name: ItemName
    guest_quick_adjust: bool = False
    increments: Increments = None
    tag_ids: list[int] = Field(default_factory=list)
    image: ImageSource = None
    expiration_tracking_enabled: bool = False
    expiration_notice_days_override: OptionalPositiveInt = None
    scan_alert_flagged: bool = False
    min_quantity: PositiveInt
    max_quantity: PositiveInt
    batch_size: PositiveInt
    restock_delivery_days: OptionalPositiveInt = None
    secondary_upcs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_quantity_bounds(self):
        if self.max_quantity <= self.min_quantity:
            raise ValueError("Maximum quantity must be greater than minimum quantity.")
        return self

    @model_validator(mode="after")
    def validate_secondary_upcs(self):
        normalized = [_validate_secondary_upc(value) for value in self.secondary_upcs if value]
        if len(normalized) != len(set(normalized)):
            raise ValueError("Secondary UPCs must be unique.")
        self.secondary_upcs = normalized
        return self


class AdminTagForm(BaseModel):
    tag_name: TagName
    color: TagColor


class AdminNotificationFormBase(BaseModel):
    email: EmailAddress128
    location_filter_ids: list[int] | None = None
    quiet_start_time: QuietTime = None
    quiet_end_time: QuietTime = None
    alert_frequency: AlertEmailFrequency = AlertEmailFrequency.HOURLY
    scan_alert_scope: ScanAlertScope = ScanAlertScope.ALL

    @model_validator(mode="after")
    def validate_quiet_hours_pair(self):
        if bool(self.quiet_start_time) != bool(self.quiet_end_time):
            raise ValueError("Quiet hours need both a start time and an end time.")
        return self

    @model_validator(mode="after")
    def validate_location_filters(self):
        if not self.location_filter_ids:
            raise ValueError("Select at least one location.")
        return self


def _notification_default(field: str) -> bool:
    return next(preference.default for preference in NOTIFICATION_PREFERENCES if preference.field == field)


class AdminNotificationForm(AdminNotificationFormBase):
    alert_for_stockout: bool = _notification_default("alert_for_stockout")
    alert_for_stockout_pred: bool = _notification_default("alert_for_stockout_pred")
    alert_for_low: bool = _notification_default("alert_for_low")
    alert_for_low_pred: bool = _notification_default("alert_for_low_pred")
    alert_for_stale_count: bool = _notification_default("alert_for_stale_count")
    alert_for_rare_takeout: bool = _notification_default("alert_for_rare_takeout")
    alert_for_count: bool = _notification_default("alert_for_count")
    alert_for_restock: bool = _notification_default("alert_for_restock")
    alert_for_takeout: bool = _notification_default("alert_for_takeout")
    alert_for_transfer: bool = _notification_default("alert_for_transfer")
    alert_for_unknown_upc: bool = _notification_default("alert_for_unknown_upc")
    alert_for_expired_stock: bool = _notification_default("alert_for_expired_stock")
    alert_for_expiring_soon: bool = _notification_default("alert_for_expiring_soon")
    alert_for_expiration_count_needed: bool = _notification_default("alert_for_expiration_count_needed")
    daily_summary: bool = _notification_default("daily_summary")
    weekly_summary: bool = _notification_default("weekly_summary")
    monthly_summary: bool = _notification_default("monthly_summary")
    yearly_summary: bool = _notification_default("yearly_summary")


class AdminSettingsForm(BaseModel):
    image: ImageSource = None
    pin: AdminPinChange = None
    user_count_allow: bool = False
    user_restock_allow: bool = False
    lead_time_days: PositiveInt
    count_last_days: PositiveInt
    alert_rare_scan_days: PositiveInt
    expiration_notice_days: PositiveInt


def _validate_secondary_upc(value: str) -> str:
    normalized = validate_upc_code(value)
    if normalized.startswith(UPC_GENERATION_PREFIX):
        raise ValueError("Secondary UPCs cannot use generated item UPCs.")
    return normalized
