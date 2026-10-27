"""Response models for the admin overview surface: dashboard tiles, settings, and pending dates."""

from pydantic import BaseModel, RootModel

from app.alerts.constants import AlertType
from app.auth.models import Agency

from .dashboard_service import AttentionCounter, AttentionSeverity, AttentionTile
from .expiration_ui_service import ExpirationEntryGroup
from .response import ExpirationOptionResponse


class AttentionTileResponse(BaseModel):
    """One dashboard tile: what needs attention, how much of it, and how hard it pushes."""

    alert_type: AlertType
    title: str
    detail: str
    severity: AttentionSeverity
    counter: AttentionCounter
    count: int
    extra: int
    sort_key: str
    sort_direction: str

    @classmethod
    def of(cls, tile: AttentionTile) -> "AttentionTileResponse":
        return cls(
            alert_type=tile.alert_type,
            title=tile.title,
            detail=tile.detail_text,
            severity=tile.severity,
            counter=tile.counter,
            count=tile.count,
            extra=tile.extra,
            sort_key=tile.sort_key,
            sort_direction=tile.sort_direction,
        )


class AttentionTileListResponse(RootModel[list[AttentionTileResponse]]):
    """Every dashboard tile in urgency order, cleared ones last."""


class PendingExpirationGroupResponse(BaseModel):
    """One item/storage pair whose tracked dates no longer add up to its counted quantity."""

    item_id: int
    storage_id: int
    item_name: str
    storage_name: str
    subtitle: str
    target_quantity: int
    allows_new_dates: bool
    allows_other: bool
    max_new_rows: int
    options: list[ExpirationOptionResponse]

    @classmethod
    def of(cls, group: ExpirationEntryGroup) -> "PendingExpirationGroupResponse":
        return cls(
            item_id=group.spec.item_id,
            storage_id=group.spec.storage_id,
            item_name=group.item.name,
            storage_name=group.storage.history_name,
            subtitle=group.spec.card_subtitle,
            target_quantity=group.spec.quantity,
            allows_new_dates=group.spec.allows_new_dates,
            allows_other=group.spec.allows_other,
            max_new_rows=group.spec.new_date_row_count,
            options=[ExpirationOptionResponse.of(option) for option in group.options],
        )


class PendingExpirationListResponse(RootModel[list[PendingExpirationGroupResponse]]):
    """Every pair still waiting on expiration dates, by item then storage."""


class ExpirationCorrectionResultResponse(BaseModel):
    """How many item/storage pairs one correction save rewrote."""

    corrected_pair_count: int


class AdminSettingsResponse(BaseModel):
    """The agency's own settings. The admin PIN is write-only and never answered back."""

    image: str | None
    user_count_allow: bool
    user_restock_allow: bool
    lead_time_days: int
    count_last_days: int
    alert_rare_scan_days: int
    expiration_notice_days: int

    @classmethod
    def of(cls, agency: Agency) -> "AdminSettingsResponse":
        return cls(
            image=agency.image,
            user_count_allow=agency.user_count_allow,
            user_restock_allow=agency.user_restock_allow,
            lead_time_days=agency.lead_time_days,
            count_last_days=agency.count_last_days,
            alert_rare_scan_days=agency.alert_rare_scan_days,
            expiration_notice_days=agency.expiration_notice_days,
        )
