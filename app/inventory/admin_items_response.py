"""Response models for the admin data screens: items and item tags."""

from typing import Final

from pydantic import BaseModel, ConfigDict, RootModel

from app.auth.models import ItemTag

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
