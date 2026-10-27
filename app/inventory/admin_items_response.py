"""Response models for the admin data screens: items, tags, and notification recipients."""

from typing import Final

from pydantic import BaseModel, ConfigDict, RootModel

from app.auth.models import ItemTag, NotificationRecipient
from app.auth.notification_preferences import NOTIFICATION_FIELDS, AlertEmailFrequency, ScanAlertScope

from .models import Item

DEFAULT_BATCH_SIZE: Final[int] = 1


class AdminItemResponse(BaseModel):
    """One item carrying every field its admin editor can change."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    upc: str
    secondary_upcs: list[str]
    guest_quick_adjust: bool
    increments: str | None
    tag_ids: list[int]
    image: str | None
    expiration_tracking_enabled: bool
    expiration_notice_days_override: int | None
    scan_alert_flagged: bool
    min_quantity: int
    max_quantity: int
    batch_size: int
    restock_delivery_days: int | None

    @classmethod
    def of(cls, item: Item) -> "AdminItemResponse":
        return cls(
            id=item.id,
            name=item.name,
            upc=item.upc,
            secondary_upcs=[code.upc for code in item.secondary_upcs if code.active],
            guest_quick_adjust=item.guest_quick_adjust,
            increments=item.increments,
            tag_ids=list(item.tag_ids or []),
            image=item.image,
            expiration_tracking_enabled=item.expiration_tracking_enabled,
            expiration_notice_days_override=item.expiration_notice_days_override,
            scan_alert_flagged=item.scan_alert_flagged,
            min_quantity=item.min_quantity,
            max_quantity=item.max_quantity,
            batch_size=item.batch_size or DEFAULT_BATCH_SIZE,
            restock_delivery_days=item.restock_delivery_days,
        )


class AdminItemListResponse(RootModel[list[AdminItemResponse]]):
    """Every active item the agency keeps."""


class TagResponse(BaseModel):
    """One item tag, with the contrasting text color its chip is drawn in."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    tag_name: str
    color: str
    text_color: str

    @classmethod
    def of(cls, tag: ItemTag) -> "TagResponse":
        return cls(id=tag.id, tag_name=tag.tag_name, color=tag.color, text_color=tag.text_color)


class TagListResponse(RootModel[list[TagResponse]]):
    """Every active tag the agency can put on an item."""


class NotificationRecipientResponse(BaseModel):
    """One alert recipient: its delivery window and scope, plus every per-alert toggle it stores."""

    id: int
    email: str
    active: bool
    location_filter_ids: list[int] | None
    quiet_start_time: str | None
    quiet_end_time: str | None
    quiet_hours_label: str
    alert_frequency: AlertEmailFrequency
    scan_alert_scope: ScanAlertScope
    alert_for_stockout: bool
    alert_for_stockout_pred: bool
    alert_for_low: bool
    alert_for_low_pred: bool
    alert_for_stale_count: bool
    alert_for_rare_takeout: bool
    alert_for_count: bool
    alert_for_restock: bool
    alert_for_takeout: bool
    alert_for_transfer: bool
    alert_for_unknown_upc: bool
    alert_for_expired_stock: bool
    alert_for_expiring_soon: bool
    alert_for_expiration_count_needed: bool
    daily_summary: bool
    weekly_summary: bool
    monthly_summary: bool
    yearly_summary: bool

    @classmethod
    def of(cls, recipient: NotificationRecipient) -> "NotificationRecipientResponse":
        return cls.model_validate(
            {
                "id": recipient.id,
                "email": recipient.email,
                "active": recipient.active,
                "location_filter_ids": list(recipient.location_filter_ids) if recipient.location_filter_ids else None,
                "quiet_start_time": recipient.quiet_start_time,
                "quiet_end_time": recipient.quiet_end_time,
                "quiet_hours_label": recipient.quiet_hours_label,
                "alert_frequency": recipient.alert_frequency,
                "scan_alert_scope": recipient.scan_alert_scope,
            }
            | {field: recipient.preference_enabled(field) for field in NOTIFICATION_FIELDS}
        )


class NotificationRecipientListResponse(RootModel[list[NotificationRecipientResponse]]):
    """Every active recipient the agency sends alerts and summaries to."""
