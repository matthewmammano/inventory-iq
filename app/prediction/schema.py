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
