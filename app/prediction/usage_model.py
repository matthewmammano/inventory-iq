"""Weighted location-level trend fitting."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.inventory.location_state_service import update_state_trend
from app.inventory.models import InventoryItemLocationState
from app.prediction.constants import CONFIDENCE_FULL_SEGMENTS, MIN_TREND_SEGMENTS
from app.prediction.segments import TrendSegment, build_count_signature, extract_segments
from app.shared.clock import utc_now_naive


@dataclass(frozen=True)
class TrendFit:
    """Persistable weighted trend fit."""

    trend_per_day: float
    confidence_percent: float
    segment_count: int


def train_location_trend(
    session: Session,
    agency_id: int,
    item_id: int,
    agency_location_id: int,
) -> InventoryItemLocationState | None:
    """Train and persist one trend row if count data changed."""
    signature = build_count_signature(session, agency_id, item_id, agency_location_id)
    existing = get_inventory_trend(session, agency_id, item_id, agency_location_id)
    if existing and existing.data_signature == signature:
        return existing

    segments = extract_segments(session, agency_id, item_id, agency_location_id)
    fit = fit_trend(segments)
    if fit is None:
        return update_state_trend(
            session,
            agency_id,
            item_id,
            agency_location_id,
            trend_per_day=None,
            confidence_percent=None,
            segment_count=0,
            data_signature=signature,
            trained_at=utc_now_naive(),
        )

    return update_state_trend(
        session,
        agency_id,
        item_id,
        agency_location_id,
        trend_per_day=fit.trend_per_day,
        confidence_percent=fit.confidence_percent,
        segment_count=fit.segment_count,
        data_signature=signature,
        trained_at=utc_now_naive(),
    )


def get_inventory_trend(
    session: Session,
    agency_id: int,
    item_id: int,
    agency_location_id: int,
) -> InventoryItemLocationState | None:
    """Return the current state row that owns persisted trend fields."""
    try:
        return (
            session.execute(
                select(InventoryItemLocationState).where(
                    InventoryItemLocationState.agency_id == agency_id,
                    InventoryItemLocationState.item_id == item_id,
                    InventoryItemLocationState.agency_location_id == agency_location_id,
                )
            )
            .scalars()
            .first()
        )
    except SQLAlchemyError:
        return None


def fit_trend(segments: list[TrendSegment]) -> TrendFit | None:
    """Fit weighted trend at today's point from segment trends."""
    if len(segments) < MIN_TREND_SEGMENTS:
        return None

    now = utc_now_naive()
    if segments[0].end_at.tzinfo is None:
        now = now.replace(tzinfo=None)
    x_values = [(segment.end_at - now).total_seconds() / 86_400 for segment in segments]
    y_values = [segment.trend_per_day for segment in segments]
    weights = [segment.weight for segment in segments]
    trend = _weighted_linear_intercept(x_values, y_values, weights)
    return TrendFit(
        trend_per_day=trend,
        confidence_percent=_confidence_percent(y_values, weights, trend, len(segments)),
        segment_count=len(segments),
    )


def _weighted_linear_intercept(
    x_values: list[float],
    y_values: list[float],
    weights: list[float],
) -> float:
    weight_total = sum(weights)
    if weight_total <= 0:
        return 0.0

    x_bar = sum(w * x for x, w in zip(x_values, weights, strict=True)) / weight_total
    y_bar = sum(w * y for y, w in zip(y_values, weights, strict=True)) / weight_total
    variance_x = sum(w * (x - x_bar) ** 2 for x, w in zip(x_values, weights, strict=True))
    if variance_x == 0:
        return y_bar

    covariance = sum(w * (x - x_bar) * (y - y_bar) for x, y, w in zip(x_values, y_values, weights, strict=True))
    slope = covariance / variance_x
    return y_bar - slope * x_bar


def _confidence_percent(
    trends: list[float],
    weights: list[float],
    fitted_trend: float,
    segment_count: int,
) -> float:
    weight_total = sum(weights)
    if weight_total <= 0:
        return 0.0

    mean = sum(w * trend for trend, w in zip(trends, weights, strict=True)) / weight_total
    variance = sum(w * (trend - mean) ** 2 for trend, w in zip(trends, weights, strict=True)) / weight_total
    spread = variance**0.5
    agreement = 1.0 if spread == 0 else abs(fitted_trend) / (abs(fitted_trend) + spread)
    volume = min(segment_count / CONFIDENCE_FULL_SEGMENTS, 1.0)
    raw_confidence = max(0.0, min(agreement * volume * 100, 100.0))
    return _smoothed_confidence_percent(raw_confidence, segment_count)


def _smoothed_confidence_percent(raw_confidence: float, segment_count: int) -> float:
    prior_confidence = 60.0
    prior_segments = 2
    blended = ((raw_confidence * segment_count) + (prior_confidence * prior_segments)) / (segment_count + prior_segments)
    max_lift = 14.0 if raw_confidence < 20 else 12.0 if raw_confidence < 40 else 8.0
    lifted_confidence = raw_confidence + min(max(blended - raw_confidence, 0.0), max_lift)
    return max(raw_confidence, min(lifted_confidence + 8.0, 95.0))
