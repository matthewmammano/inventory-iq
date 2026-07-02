"""Restock analysis for one agency location."""

from datetime import datetime
from math import floor

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import Agencies, AgencyLocations
from app.inventory.balance_service import get_location_last_counted_dates
from app.inventory.location_state_policy import days_to_threshold, effective_lead_time_days
from app.inventory.location_state_service import recompute_item_location_state
from app.inventory.models import InventoryItemLocationState, Items
from app.prediction.constants import MAX_EFFECTIVE_DAILY_USAGE, MIN_EFFECTIVE_DAILY_USAGE
from app.prediction.estimator import reorder_date
from app.prediction.formatting import format_usage_rate, rounded_confidence_percent
from app.shared.timezone_utils import convert_utc_to_local


class BulkService:
    """Build template-ready restock rows for a selected agency location."""

    @staticmethod
    def get_active_items(session: Session, agency_id: int) -> list[Items]:
        return list(
            session.execute(
                select(Items).where(Items.agency_id == agency_id, Items.active.is_(True)).order_by(Items.last_accessed.desc().nulls_last())
            )
            .scalars()
            .all()
        )

    @staticmethod
    def get_restock_analysis(
        session: Session,
        agency_id: int,
        agency_location_id: int,
    ) -> list[dict]:
        try:
            agency_settings = session.get(Agencies, agency_id)
            items = BulkService.get_active_items(session, agency_id)
            item_ids = [item.id for item in items]
            location_states_by_item_id = BulkService._location_states_by_item_id(session, agency_id, agency_location_id, items)
            last_counted_at_by_item_id = BulkService._last_counted_at_by_item_id(
                session,
                agency_id,
                agency_location_id,
                item_ids,
                agency_settings.timezone if agency_settings else "UTC",
            )
            rows = [
                BulkService._analyze_item(
                    item,
                    agency_settings,
                    location_states_by_item_id.get(item.id),
                    last_counted_at_by_item_id.get(item.id),
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
        state: InventoryItemLocationState | None,
        last_counted_at: datetime | None,
    ) -> dict:
        current_quantity = int(state.total_quantity if state else 0)
        min_qty = int(item.min_quantity or 0)
        max_qty = int(item.max_quantity or 0)
        batch_size = int(item.batch_size or 0)
        lead_time_days = effective_lead_time_days(
            agency.lead_time_days if agency else None,
            item.restock_delivery_days,
        )
        persisted_trend = state.trend_per_day if state is not None else None
        has_trained_trend = persisted_trend is not None and last_counted_at is not None
        daily_usage = BulkService._trained_daily_usage(persisted_trend) if has_trained_trend else None
        days_low = days_to_threshold(current_quantity, -daily_usage, min_qty) if daily_usage is not None else None
        days_out = days_to_threshold(current_quantity, -daily_usage, 0) if daily_usage is not None else None
        order_amount = (
            BulkService._calculate_order_amount(
                current_total=current_quantity,
                max_qty=max_qty,
                daily_usage=daily_usage,
                delivery_days=lead_time_days,
                batch_size=batch_size,
                days_until_low=days_low,
            )
            if daily_usage is not None
            else None
        )

        return {
            "item": item,
            "current_total": current_quantity,
            "projected_lead_time_total": round(current_quantity - daily_usage * lead_time_days) if daily_usage is not None else None,
            "min_quantity": min_qty,
            "max_quantity": max_qty,
            "gap_to_min": max(min_qty - current_quantity, 0),
            "lead_time_days": lead_time_days,
            "suggested_reorder_date": reorder_date(days_low, lead_time_days) if days_low is not None else None,
            "last_counted_at": last_counted_at,
            "days_until_low": days_low,
            "days_until_stockout": floor(days_out) if days_out is not None else None,
            "order_amount": order_amount,
            "order_amount_display": BulkService._format_order_amount_display(order_amount, days_low),
            "confidence_percent": state.confidence_percent if has_trained_trend and state else None,
            "confidence_display": rounded_confidence_percent(state.confidence_percent if has_trained_trend and state else None),
            "daily_usage_rate": daily_usage,
            "usage_display": format_usage_rate(daily_usage),
            "used_fallback": not has_trained_trend,
        }

    @staticmethod
    def _trained_daily_usage(trend_per_day: float | None) -> float | None:
        if trend_per_day is None:
            return None
        return min(
            max(max(0.0, -float(trend_per_day)), MIN_EFFECTIVE_DAILY_USAGE),
            MAX_EFFECTIVE_DAILY_USAGE,
        )

    @staticmethod
    def _location_states_by_item_id(
        session: Session,
        agency_id: int,
        agency_location_id: int,
        items: list[Items],
    ) -> dict[int, InventoryItemLocationState]:
        if not items:
            return {}
        states: dict[int, InventoryItemLocationState] = {}
        for item in items:
            state = recompute_item_location_state(session, agency_id, item.id, agency_location_id)
            if state is not None:
                states[item.id] = state
        return states

    @staticmethod
    def _last_counted_at_by_item_id(
        session: Session,
        agency_id: int,
        agency_location_id: int,
        item_ids: list[int],
        agency_timezone: str,
    ) -> dict[int, datetime]:
        latest: dict[int, datetime] = {}
        for item_id, counted_at in get_location_last_counted_dates(session, agency_id, agency_location_id, item_ids).items():
            local_time = convert_utc_to_local(counted_at, agency_timezone)
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
