"""Restock analysis for one agency location."""

from datetime import datetime
from math import floor

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import Agencies, AgencyLocations
from app.inventory.constants import OperationType
from app.inventory.item_queries import list_items
from app.inventory.models import ActionLogs, Items
from app.prediction.constants import MAX_EFFECTIVE_DAILY_USAGE, MIN_EFFECTIVE_DAILY_USAGE
from app.prediction.estimator import (
    days_to_threshold,
    effective_lead_time_days,
    reorder_date,
)
from app.prediction.formatting import rounded_confidence_percent
from app.prediction.models import InventoryTrend
from app.prediction.segments import get_location_storage_ids
from app.shared.timezone_utils import convert_utc_to_local


class BulkService:
    """Build template-ready restock rows for a selected agency location."""

    @staticmethod
    def get_restock_analysis(
        session: Session,
        agency_id: int,
        agency_location_id: int,
    ) -> list[dict]:
        try:
            agency = session.execute(select(Agencies).where(Agencies.id == agency_id)).scalars().first()
            items = list_items(agency_id, include_inactive=False, order_by_last_accessed=True, session=session)
            item_ids = [item.id for item in items]
            storage_ids = get_location_storage_ids(session, agency_id, agency_location_id)
            quantities = BulkService._location_quantities(session, agency_id, item_ids, storage_ids)
            trends = BulkService._location_trends(session, agency_id, agency_location_id, item_ids)
            last_counts = BulkService._last_counted_dates(session, agency_id, storage_ids, agency.timezone if agency else "UTC")
            rows = [
                BulkService._analyze_item(
                    item,
                    agency,
                    quantities.get(item.id, 0),
                    trends.get(item.id),
                    last_counts.get(item.id),
                )
                for item in items
            ]
            rows.sort(
                key=lambda row: (
                    float("inf") if row["days_until_stockout"] is None else row["days_until_stockout"],
                    -(row["order_amount"] or 0),
                    row["current_total"],
                    row["item"].name,
                )
            )
            return rows
        except Exception:
            logger.exception(
                "Restock analysis failed",
                extra={"agency_id": agency_id, "agency_location_id": agency_location_id},
            )
            raise

    @staticmethod
    def get_location(session: Session, agency_id: int, agency_location_id: int) -> AgencyLocations | None:
        return (
            session.execute(
                select(AgencyLocations).where(
                    AgencyLocations.id == agency_location_id,
                    AgencyLocations.agency_id == agency_id,
                )
            )
            .scalars()
            .first()
        )

    @staticmethod
    def _analyze_item(
        item: Items,
        agency: Agencies | None,
        current_quantity: int,
        trend: InventoryTrend | None,
        last_counted_at: datetime | None,
    ) -> dict:
        min_qty = int(item.min_quantity or 0)
        max_qty = int(item.max_quantity or 0)
        batch_size = int(item.batch_size or 0)
        lead_time_days = effective_lead_time_days(
            agency.lead_time_days if agency else None,
            item.restock_delivery_days,
        )
        trend_per_day = trend.trend_per_day if trend else -float(item.prior_daily_usage or 0)
        daily_usage = min(
            max(max(0.0, -float(trend_per_day)), MIN_EFFECTIVE_DAILY_USAGE),
            MAX_EFFECTIVE_DAILY_USAGE,
        )

        days_low = days_to_threshold(current_quantity, -daily_usage, min_qty)
        days_out = days_to_threshold(current_quantity, -daily_usage, 0)
        order_amount = BulkService._calculate_order_amount(
            current_total=current_quantity,
            max_qty=max_qty,
            daily_usage=daily_usage,
            delivery_days=lead_time_days,
            batch_size=batch_size,
            days_until_low=days_low,
        )

        return {
            "item": item,
            "current_total": current_quantity,
            "projected_lead_time_total": round(current_quantity - daily_usage * lead_time_days),
            "min_quantity": min_qty,
            "max_quantity": max_qty,
            "gap_to_min": max(min_qty - current_quantity, 0),
            "lead_time_days": lead_time_days,
            "suggested_reorder_date": reorder_date(days_low, lead_time_days),
            "last_counted_at": last_counted_at,
            "days_until_low": days_low,
            "days_until_stockout": floor(days_out) if days_out is not None else None,
            "order_amount": order_amount,
            "order_amount_display": BulkService._format_order_amount_display(order_amount, days_low),
            "confidence_percent": trend.confidence_percent if trend else None,
            "confidence_display": rounded_confidence_percent(trend.confidence_percent if trend else None),
            "daily_usage_rate": daily_usage,
            "used_fallback": trend is None,
        }

    @staticmethod
    def _location_quantities(
        session: Session,
        agency_id: int,
        item_ids: list[int],
        storage_ids: list[int],
    ) -> dict[int, int]:
        if not item_ids or not storage_ids:
            return {}

        rows = session.execute(
            select(
                ActionLogs.item_id,
                ActionLogs.operation_type,
                ActionLogs.from_location_id,
                ActionLogs.to_location_id,
                ActionLogs.quantity_delta,
            )
            .where(
                ActionLogs.agency_id == agency_id,
                ActionLogs.item_id.in_(item_ids),
                (ActionLogs.from_location_id.in_(storage_ids) | ActionLogs.to_location_id.in_(storage_ids)),
            )
            .order_by(ActionLogs.time_scanned, ActionLogs.id)
        )

        by_item_storage: dict[int, dict[int, int]] = {}
        storage_set = set(storage_ids)
        for item_id, operation, from_storage_id, to_storage_id, quantity in rows:
            if item_id is None:
                continue
            quantities = by_item_storage.setdefault(item_id, {})
            if operation == OperationType.COUNT and to_storage_id in storage_set:
                quantities[to_storage_id] = quantity
                continue
            if to_storage_id in storage_set:
                quantities[to_storage_id] = quantities.get(to_storage_id, 0) + quantity
            if from_storage_id in storage_set:
                quantities[from_storage_id] = quantities.get(from_storage_id, 0) - quantity

        return {item_id: sum(quantities.values()) for item_id, quantities in by_item_storage.items()}

    @staticmethod
    def _location_trends(
        session: Session,
        agency_id: int,
        agency_location_id: int,
        item_ids: list[int],
    ) -> dict[int, InventoryTrend]:
        if not item_ids:
            return {}
        rows = session.execute(
            select(InventoryTrend).where(
                InventoryTrend.agency_id == agency_id,
                InventoryTrend.agency_location_id == agency_location_id,
                InventoryTrend.item_id.in_(item_ids),
            )
        ).scalars()
        return {trend.item_id: trend for trend in rows}

    @staticmethod
    def _last_counted_dates(
        session: Session,
        agency_id: int,
        storage_ids: list[int],
        agency_timezone: str,
    ) -> dict[int, datetime]:
        if not storage_ids:
            return {}

        rows = session.execute(
            select(ActionLogs.item_id, ActionLogs.time_scanned)
            .where(
                ActionLogs.agency_id == agency_id,
                ActionLogs.operation_type == OperationType.COUNT,
                ActionLogs.to_location_id.in_(storage_ids),
            )
            .order_by(ActionLogs.time_scanned)
        )
        latest: dict[int, datetime] = {}
        for item_id, scanned_at in rows:
            if item_id is not None and scanned_at is not None:
                local_time = convert_utc_to_local(scanned_at, agency_timezone)
                if local_time is not None:
                    latest[item_id] = local_time
        return latest

    @staticmethod
    def _calculate_order_amount(
        current_total: int,
        max_qty: int,
        daily_usage: float,
        delivery_days: int,
        batch_size: int,
        days_until_low: float | None,
    ) -> int | None:
        if max_qty <= 0:
            return 0
        if days_until_low is None:
            return None

        needed = max_qty - current_total + daily_usage * max(delivery_days, 0)
        if needed <= 0:
            return 0
        if batch_size > 0:
            return int(((needed + batch_size - 1) // batch_size) * batch_size)
        return int(needed)

    @staticmethod
    def _format_order_amount_display(
        order_amount: int | None,
        days_until_low: float | None,
    ) -> str:
        if days_until_low is None or order_amount is None:
            return "N/A"
        return str(order_amount)
