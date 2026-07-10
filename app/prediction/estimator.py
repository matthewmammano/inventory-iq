"""Location-level inventory projection from persisted trend parameters."""

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.inventory.location_state_policy import bound_daily_usage
from app.inventory.location_state_service import recompute_item_location_state
from app.inventory.models import Item
from app.prediction.usage_model import get_inventory_trend


@dataclass(frozen=True)
class LocationProjection:
    """Current stock plus learned usage trend for one item/location."""

    item_id: int
    agency_location_id: int
    current_quantity: int
    trend_per_day: float
    confidence_percent: float | None
    segment_count: int
    used_fallback: bool

    @property
    def daily_usage(self) -> float:
        return bound_daily_usage(max(0.0, -float(self.trend_per_day)))


def project_location_item(
    session: Session,
    agency_id: int,
    item: Item,
    agency_location_id: int,
) -> LocationProjection:
    """Return the current truth plus persisted location trend for one item."""
    location_state = get_inventory_trend(session, agency_id, item.id, agency_location_id)
    if location_state is None:
        location_state = recompute_item_location_state(session, agency_id, item.id, agency_location_id)
    trend_per_day = location_state.trend_per_day if location_state is not None else None
    has_trained_trend = trend_per_day is not None
    fallback_trend = -float(item.prior_daily_usage or 0)
    return LocationProjection(
        item_id=item.id,
        agency_location_id=agency_location_id,
        current_quantity=get_location_item_quantity(session, agency_id, item.id, agency_location_id),
        trend_per_day=float(trend_per_day) if trend_per_day is not None else fallback_trend,
        confidence_percent=location_state.confidence_percent if has_trained_trend and location_state else None,
        segment_count=location_state.segment_count if has_trained_trend and location_state else 0,
        used_fallback=not has_trained_trend,
    )


def get_location_item_quantity(
    session: Session,
    agency_id: int,
    item_id: int,
    agency_location_id: int,
) -> int:
    """Current item quantity summed across storages in one agency location."""
    state = get_inventory_trend(session, agency_id, item_id, agency_location_id)
    if state is None:
        state = recompute_item_location_state(session, agency_id, item_id, agency_location_id)
    return int(state.total_quantity if state else 0)


def projected_quantity(current_quantity: int, trend_per_day: float, days: float) -> float:
    """Project quantity after a number of days, never below zero."""
    return max(float(current_quantity) + trend_per_day * days, 0.0)


def reorder_date(days_until_low: float | None, lead_time_days: int) -> date | None:
    """Return the latest suggested order date before hitting minimum stock."""
    if days_until_low is None:
        return None
    return date.today() + timedelta(days=max(days_until_low - max(lead_time_days, 0), 0.0))
