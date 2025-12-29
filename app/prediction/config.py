"""
Configuration constants for the prediction system.
"""

from datetime import timedelta
from typing import Final


class PredictionConfig:
    """Configuration constants for prediction system."""

    # Time window for restock validation (global variable for easy changes)
    RESTOCK_VALIDATION_HOURS: Final[int] = 48
    RESTOCK_VALIDATION_DELTA: Final[timedelta] = timedelta(
        hours=RESTOCK_VALIDATION_HOURS
    )

    # ML model configuration
    MIN_DATA_POINTS_FOR_ML: Final[int] = 3
    ML_TIME_DECAY_FACTOR: Final[float] = (
        0.95  # Higher values give more weight to recent data
    )

    # Combination weights for ML vs Prior predictions
    MIN_CONFIDENCE_THRESHOLD: Final[float] = 0.6

    # Default weights when both ML and Prior are available
    DEFAULT_ML_WEIGHT: Final[float] = 0.7
    DEFAULT_PRIOR_WEIGHT: Final[float] = 0.3
