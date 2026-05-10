"""Restock analysis for one agency location."""

from datetime import datetime

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import Agencies, AgencyLocations
from app.inventory.constants import OperationType
from app.inventory.item_queries import list_items
from app.inventory.models import ActionLogs, Items
from app.prediction.estimator import (
    days_to_threshold,
    effective_lead_time_days,
    project_location_item,
    reorder_date,
)
from app.prediction.formatting import rounded_confidence_percent
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
            agency = (
                session.execute(select(Agencies).where(Agencies.id == agency_id)).scalars().first()
            )
            items = list_items(
                agency_id, include_inactive=False, order_by_last_accessed=True, session=session
            )
            rows = [
                BulkService._analyze_item(session, agency_id, agency_location_id, item, agency)
                for item in items
            ]
            rows.sort(
                key=lambda row: (
                    float("inf")
                    if row["days_until_stockout"] is None
                    else row["days_until_stockout"],
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
    def get_location(
        session: Session, agency_id: int, agency_location_id: int
    ) -> AgencyLocations | None:
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
        session: Session,
        agency_id: int,
        agency_location_id: int,
        item: Items,
        agency: Agencies | None,
    ) -> dict:
        agency_timezone = agency.timezone if agency else "UTC"
        min_qty = int(item.min_quantity or 0)
        max_qty = int(item.max_quantity or 0)
        batch_size = int(item.batch_size or 0)
        lead_time_days = effective_lead_time_days(
            agency.lead_time_days if agency else None,
            item.restock_delivery_days,
        )
        projection = project_location_item(session, agency_id, item, agency_location_id)

        days_low = days_to_threshold(projection.current_quantity, projection.trend_per_day, min_qty)
        days_out = days_to_threshold(projection.current_quantity, projection.trend_per_day, 0)
        order_amount = BulkService._calculate_order_amount(
            current_total=projection.current_quantity,
            max_qty=max_qty,
            daily_usage=projection.daily_usage,
            delivery_days=lead_time_days,
            batch_size=batch_size,
            days_until_low=days_low,
        )

        return {
            "item": item,
            "current_total": projection.current_quantity,
            "projected_lead_time_total": round(
                max(projection.current_quantity + projection.trend_per_day * lead_time_days, 0)
            ),
            "min_quantity": min_qty,
            "max_quantity": max_qty,
            "gap_to_min": projection.current_quantity - min_qty,
            "lead_time_days": lead_time_days,
            "suggested_reorder_date": reorder_date(days_low, lead_time_days),
            "last_counted_at": BulkService._get_last_counted_at(
                session, agency_id, item.id, agency_location_id, agency_timezone
            ),
            "days_until_low": days_low,
            "days_until_stockout": days_out,
            "order_amount": order_amount,
            "order_amount_display": BulkService._format_order_amount_display(
                order_amount, days_low
            ),
            "confidence_percent": projection.confidence_percent,
            "confidence_display": rounded_confidence_percent(projection.confidence_percent),
            "daily_usage_rate": projection.daily_usage,
            "used_fallback": projection.used_fallback,
        }

    @staticmethod
    def _get_last_counted_at(
        session: Session,
        agency_id: int,
        item_id: int,
        agency_location_id: int,
        agency_timezone: str,
    ) -> datetime | None:
        storage_ids = get_location_storage_ids(session, agency_id, agency_location_id)
        if not storage_ids:
            return None
        row = (
            session.execute(
                select(ActionLogs)
                .where(
                    ActionLogs.agency_id == agency_id,
                    ActionLogs.item_id == item_id,
                    ActionLogs.operation_type == OperationType.COUNT,
                    ActionLogs.to_location_id.in_(storage_ids),
                )
                .order_by(ActionLogs.time_scanned.desc())
                .limit(1)
            )
            .scalars()
            .first()
        )
        return convert_utc_to_local(row.time_scanned, agency_timezone) if row else None

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
