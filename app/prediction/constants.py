"""Prediction module constants."""

from typing import Final

MIN_TREND_SEGMENTS: Final[int] = 2
CONFIDENCE_FULL_SEGMENTS: Final[int] = 10
COUNT_CLUSTER_HOURS: Final[int] = 24
RESTOCK_VALIDATION_DAYS: Final[int] = 30

RECENCY_WEIGHT_30_DAYS: Final[float] = 1.0
RECENCY_WEIGHT_90_DAYS: Final[float] = 0.75
RECENCY_WEIGHT_365_DAYS: Final[float] = 0.40
RECENCY_WEIGHT_OLD: Final[float] = 0.15

MODEL_SIGNATURE_VERSION: Final[str] = "location-trend-v1"

MIN_EFFECTIVE_DAILY_USAGE: Final[float] = 0.0
MAX_EFFECTIVE_DAILY_USAGE: Final[float] = 99.0
