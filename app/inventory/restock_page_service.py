"""Template DTOs for the admin restock page."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.inventory.expiration_ui_service import ExpirationBreakdown, expiration_breakdowns_by_item
from app.inventory.ui import get_days_until_low_class, get_inventory_level_class, get_order_quantity_class
from app.prediction.bulk_service import BulkService


@dataclass(frozen=True, slots=True)
class RestockPageRow:
    item: Any
    current_total: int
    projected_lead_time_total: int | None
    min_quantity: int
    max_quantity: int
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
    used_fallback: bool
    current_total_class: str
    projected_total_class: str
    min_quantity_class: str
    days_class: str
    order_class: str
    expiration_breakdown: ExpirationBreakdown | None


def build_restock_page_rows(session: Session, agency_id: int, agency_location_id: int) -> list[RestockPageRow]:
    expiration_breakdowns = expiration_breakdowns_by_item(session, agency_id, agency_location_id)
    analysis_rows = BulkService.get_restock_analysis(session, agency_id, agency_location_id)
    return [_page_row(row, expiration_breakdowns.get(row["item"].id)) for row in analysis_rows]


def _page_row(row: dict[str, Any], expiration_breakdown: ExpirationBreakdown | None) -> RestockPageRow:
    current_total = int(row.get("current_total") or 0)
    min_quantity = int(row.get("min_quantity") or 0)
    projected_total = int(row.get("projected_lead_time_total") or 0)
    classes = _restock_cell_classes(current_total, min_quantity, projected_total)
    return RestockPageRow(
        item=row["item"],
        current_total=current_total,
        projected_lead_time_total=row["projected_lead_time_total"],
        min_quantity=min_quantity,
        max_quantity=int(row.get("max_quantity") or 0),
        gap_to_min=int(row.get("gap_to_min") or 0),
        lead_time_days=int(row.get("lead_time_days") or 0),
        suggested_reorder_date=row["suggested_reorder_date"],
        last_counted_at=row["last_counted_at"],
        days_until_low=row["days_until_low"],
        days_until_stockout=row["days_until_stockout"],
        order_amount=row["order_amount"],
        order_amount_display=row["order_amount_display"],
        confidence_percent=row["confidence_percent"],
        confidence_display=row["confidence_display"],
        daily_usage_rate=row["daily_usage_rate"],
        usage_display=row["usage_display"],
        used_fallback=row["used_fallback"],
        current_total_class=classes["current_total_class"],
        projected_total_class=classes.get("projected_total_class", ""),
        min_quantity_class=classes.get("min_quantity_class", ""),
        days_class=get_days_until_low_class(row["days_until_stockout"]),
        order_class=get_order_quantity_class(row["order_amount"]),
        expiration_breakdown=expiration_breakdown,
    )


def _restock_cell_classes(current_total: int, min_quantity: int, projected_total: int) -> dict[str, str]:
    classes = {"current_total_class": get_inventory_level_class(current_total)}

    if current_total <= 0:
        classes["current_total_class"] = "restock-critical"
    elif current_total <= min_quantity:
        classes["current_total_class"] = "restock-low"
        classes["min_quantity_class"] = "restock-low"

    if projected_total <= 0:
        classes["projected_total_class"] = "restock-projected-stockout"
    elif projected_total <= min_quantity:
        classes["projected_total_class"] = "restock-projected-low"
        classes.setdefault("min_quantity_class", "restock-projected-low")

    return classes
