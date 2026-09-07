"""Pydantic models for prediction outputs."""

from pydantic import BaseModel, Field


class LocationPredictionResponse(BaseModel):
    """Prediction output for one item at one agency location."""

    item_id: int
    agency_location_id: int
    current_quantity: int
    trend_per_day: float
    confidence_percent: float | None = Field(default=None, ge=0, le=100)
    days_until_low: float | None = Field(default=None, ge=0)


class TrendChartPoint(BaseModel):
    """One point on an item/location trend chart."""

    at: str
    quantity: float
    operation: str | None = None
    expected_quantity: float | None = None
    discrepancy: float | None = None


class ItemTrendChartResponse(BaseModel):
    """Historical item/location trend chart payload."""

    item_id: int
    item_name: str
    agency_location_id: int
    location_name: str
    count_points: list[TrendChartPoint]
    operation_points: list[TrendChartPoint]
    trendline_points: list[TrendChartPoint]
    trend_per_day: float | None = None
    trend_rate_display: str | None = None
    confidence_percent: float | None = Field(default=None, ge=0, le=100)
