"""Response models for the admin reports: stock levels, restock, and the history log."""

from datetime import date, datetime
from typing import Final

from pydantic import BaseModel

from app.auth.models import Location, Storage
from app.inventory.count_page_service import InventoryCountPage, InventoryCountPageRow
from app.inventory.expiration_ui_service import ExpirationBreakdown
from app.inventory.models import ActionLog
from app.inventory.report_email_service import EmailDeliveryResult, ReportEmailOutcome
from app.inventory.restock_page_service import RestockPageRow
from app.shared.pagination import PageWindow

from .constants import TAKEOUT_LABEL, OperationType

ALL_LOCATIONS_NAME: Final[str] = "All Locations"
MISSING_ITEM_LABEL: Final[str] = "None"


class ReportStorageResponse(BaseModel):
    """One storage column of a stock levels table."""

    id: int
    name: str

    @classmethod
    def of(cls, storage: Storage) -> "ReportStorageResponse":
        return cls(id=storage.id, name=storage.name)


class ReportLocationResponse(BaseModel):
    """The location a report is about; null ids mean every location at once."""

    id: int | None
    name: str

    @classmethod
    def of(cls, location: Location | None) -> "ReportLocationResponse":
        if location is None:
            return cls(id=None, name=ALL_LOCATIONS_NAME)
        return cls(id=location.id, name=location.name)


class ExpirationBreakdownResponse(BaseModel):
    """How one item's stock in one location is spread across expiration dates."""

    soonest_date: date | None
    expired_count: int
    expiring_soon_count: int
    good_count: int
    missing_count: int

    @classmethod
    def of(cls, breakdown: ExpirationBreakdown | None) -> "ExpirationBreakdownResponse | None":
        if breakdown is None:
            return None
        return cls(
            soonest_date=breakdown.soonest_date,
            expired_count=breakdown.expired_count,
            expiring_soon_count=breakdown.expiring_soon_count,
            good_count=breakdown.good_count,
            missing_count=breakdown.missing_count,
        )


class StorageCountResponse(BaseModel):
    """What one storage holds of one item."""

    storage_id: int
    quantity: int


class StockLevelRowResponse(BaseModel):
    """One item's row of the stock levels table."""

    item_id: int
    item_name: str
    minimum_quantity: int
    storage_counts: list[StorageCountResponse]
    total: int
    expiration: ExpirationBreakdownResponse | None

    @classmethod
    def of(cls, row: InventoryCountPageRow) -> "StockLevelRowResponse":
        return cls(
            item_id=row.item.id,
            item_name=row.item.name,
            minimum_quantity=row.item.min_quantity,
            storage_counts=[StorageCountResponse(storage_id=storage_id, quantity=quantity) for storage_id, quantity in row.storage_counts.items()],
            total=row.total,
            expiration=ExpirationBreakdownResponse.of(row.expiration_breakdown),
        )


class StockLevelsReportResponse(BaseModel):
    """What every item holds right now in one location, storage by storage."""

    location: ReportLocationResponse
    expiration_notice_days: int
    storages: list[ReportStorageResponse]
    rows: list[StockLevelRowResponse]

    @classmethod
    def of(cls, location: Location | None, page: InventoryCountPage, expiration_notice_days: int) -> "StockLevelsReportResponse":
        return cls(
            location=ReportLocationResponse.of(location),
            expiration_notice_days=expiration_notice_days,
            storages=[ReportStorageResponse.of(storage) for storage in page.storages],
            rows=[StockLevelRowResponse.of(row) for row in page.inventory_data],
        )


class RestockRowResponse(BaseModel):
    """One item's restock analysis, with the severity classes the table colors cells by."""

    item_id: int
    item_name: str
    current_total: int
    projected_lead_time_total: int | None
    minimum_quantity: int
    maximum_quantity: int
    gap_to_min: int
    lead_time_days: int
    suggested_reorder_date: date | datetime | None
    last_counted_at: datetime | None
    days_until_low: float | None
    days_until_stockout: int | None
    order_amount: int | None
    order_amount_display: str
    confidence_percent: float | None
    confidence_display: int | None
    daily_usage_rate: float | None
    usage_display: str | None
    current_total_class: str
    projected_total_class: str
    min_quantity_class: str
    expiration: ExpirationBreakdownResponse | None

    @classmethod
    def of(cls, row: RestockPageRow) -> "RestockRowResponse":
        return cls(
            item_id=row.item.id,
            item_name=row.item.name,
            current_total=row.current_total,
            projected_lead_time_total=row.projected_lead_time_total,
            minimum_quantity=row.min_quantity,
            maximum_quantity=row.max_quantity,
            gap_to_min=row.gap_to_min,
            lead_time_days=row.lead_time_days,
            suggested_reorder_date=row.suggested_reorder_date,
            last_counted_at=row.last_counted_at,
            days_until_low=row.days_until_low,
            days_until_stockout=row.days_until_stockout,
            order_amount=row.order_amount,
            order_amount_display=row.order_amount_display,
            confidence_percent=row.confidence_percent,
            confidence_display=row.confidence_display,
            daily_usage_rate=row.daily_usage_rate,
            usage_display=row.usage_display,
            current_total_class=row.current_total_class,
            projected_total_class=row.projected_total_class,
            min_quantity_class=row.min_quantity_class,
            expiration=ExpirationBreakdownResponse.of(row.expiration_breakdown),
        )


class RestockReportResponse(BaseModel):
    """What one location should reorder, newest prediction first."""

    location: ReportLocationResponse
    rows: list[RestockRowResponse]

    @classmethod
    def of(cls, location: Location | None, rows: list[RestockPageRow]) -> "RestockReportResponse":
        return cls(location=ReportLocationResponse.of(location), rows=[RestockRowResponse.of(row) for row in rows])


class HistoryRowResponse(BaseModel):
    """One logged inventory action, as the history table reads it."""

    id: int
    at: datetime
    item_name: str
    operation: OperationType
    quantity: int
    from_label: str
    to_label: str
    admin_action: bool
    expiration_summary: str

    @classmethod
    def of(cls, log: ActionLog) -> "HistoryRowResponse":
        return cls(
            id=log.id,
            at=log.time_scanned,
            item_name=log.item.name if log.item else MISSING_ITEM_LABEL,
            operation=log.operation_type,
            quantity=log.quantity,
            from_label=log.from_storage.history_name if log.from_storage else log.operation_type.value,
            to_label=log.to_storage.history_name if log.to_storage else TAKEOUT_LABEL,
            admin_action=log.admin_action,
            expiration_summary=log.expiration_summary,
        )


class HistoryReportResponse(BaseModel):
    """One page of action history, plus the window the caller draws its own pager from."""

    location: ReportLocationResponse
    sort_key: str
    descending: bool
    page: int
    page_size: int
    total_pages: int
    total_rows: int
    rows: list[HistoryRowResponse]

    @classmethod
    def of(
        cls,
        location: Location | None,
        window: PageWindow,
        *,
        sort_key: str,
        descending: bool,
        logs: list[ActionLog],
    ) -> "HistoryReportResponse":
        return cls(
            location=ReportLocationResponse.of(location),
            sort_key=sort_key,
            descending=descending,
            page=window.current_page,
            page_size=window.page_size,
            total_pages=window.total_pages,
            total_rows=window.total_rows,
            rows=[HistoryRowResponse.of(log) for log in logs],
        )


class ReportEmailResultResponse(BaseModel):
    """How many of the selected recipients one report email reached."""

    outcome: ReportEmailOutcome
    sent: int
    total: int

    @classmethod
    def of(cls, result: EmailDeliveryResult) -> "ReportEmailResultResponse":
        return cls(outcome=result.outcome, sent=result.sent, total=result.total)
