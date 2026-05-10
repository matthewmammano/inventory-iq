"""Weighted location-level trend fitting."""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.prediction.constants import CONFIDENCE_FULL_SEGMENTS, MIN_TREND_SEGMENTS
from app.prediction.models import InventoryTrend
from app.prediction.segments import TrendSegment, build_count_signature, extract_segments
from app.shared.clock import utc_now


@dataclass(frozen=True)
class TrendFit:
    trend_per_day: float
    confidence_percent: int
    segment_count: int


def train_location_trend(
    session: Session,
    agency_id: int,
    item_id: int,
    agency_location_id: int,
) -> InventoryTrend | None:
    """Train and persist one trend row if count data changed."""
    signature = build_count_signature(session, agency_id, item_id, agency_location_id)
    existing = get_inventory_trend(session, agency_id, item_id, agency_location_id)
    if existing and existing.data_signature == signature:
        return existing

    segments = extract_segments(session, agency_id, item_id, agency_location_id)
    fit = fit_trend(segments)
    if fit is None:
        if existing:
            session.delete(existing)
        return None

    trend = existing or InventoryTrend(
        agency_id=agency_id,
        item_id=item_id,
        agency_location_id=agency_location_id,
    )
    trend.trend_per_day = fit.trend_per_day
    trend.confidence_percent = fit.confidence_percent
    trend.segment_count = fit.segment_count
    trend.data_signature = signature
    trend.trained_at = utc_now()
    session.add(trend)
    return trend


def get_inventory_trend(
    session: Session,
    agency_id: int,
    item_id: int,
    agency_location_id: int,
) -> InventoryTrend | None:
    try:
        return (
            session.execute(
                select(InventoryTrend).where(
                    InventoryTrend.agency_id == agency_id,
                    InventoryTrend.item_id == item_id,
                    InventoryTrend.agency_location_id == agency_location_id,
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

    now = utc_now()
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

    covariance = sum(
        w * (x - x_bar) * (y - y_bar) for x, y, w in zip(x_values, y_values, weights, strict=True)
    )
    slope = covariance / variance_x
    return y_bar - slope * x_bar


def _confidence_percent(
    trends: list[float],
    weights: list[float],
    fitted_trend: float,
    segment_count: int,
) -> int:
    weight_total = sum(weights)
    if weight_total <= 0:
        return 0

    mean = sum(w * trend for trend, w in zip(trends, weights, strict=True)) / weight_total
    variance = (
        sum(w * (trend - mean) ** 2 for trend, w in zip(trends, weights, strict=True))
        / weight_total
    )
    spread = variance**0.5
    agreement = 1.0 if spread == 0 else abs(fitted_trend) / (abs(fitted_trend) + spread)
    volume = min(segment_count / CONFIDENCE_FULL_SEGMENTS, 1.0)
    raw = max(0.0, min(agreement * volume, 1.0))
    return min(100, ceil(raw * 10) * 10) if raw > 0 else 0
