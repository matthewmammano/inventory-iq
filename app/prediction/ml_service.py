"""
ML-based trendline calculation with time-weighted influence and confidence scoring.

Uses regression analysis with time decay to predict daily usage patterns
from admin operation data points.
"""

from dataclasses import dataclass

import numpy as np
from loguru import logger
from sqlalchemy.orm import Session

from app.db import get_session

from .config import PredictionConfig
from .data_collection import DataPoint, DataPointCollector


@dataclass
class MLPredictionResult:
    """Result from ML prediction analysis."""

    daily_usage_rate: float  # Items per day (negative = consumption)
    confidence_score: float  # R² score (0-1, higher is better)
    data_point_count: int
    date_range_days: int
    trend_direction: str  # 'increasing', 'decreasing', 'stable'
    prediction_type: str = "ML"


class MLPredictionService:
    """Machine learning service for inventory usage prediction."""

    @staticmethod
    def predict_usage_rate(
        db_session: Session, user_id: int, item_id: int, location_id: int
    ) -> MLPredictionResult | None:
        """
        Predict daily usage rate using ML with time-weighted data points.

        Args:
            db_session: Database session
            user_id: User ID
            item_id: Item ID
            location_id: Location ID

        Returns:
            MLPredictionResult if sufficient data, None otherwise
        """
        # Allow callers to pass a Session or rely on the helper-managed session.
        use_external_session = db_session is not None

        try:
            if use_external_session:
                data_points = DataPointCollector.collect_data_points(
                    db_session, user_id, item_id, location_id
                )
            else:
                with get_session() as _s:
                    data_points = DataPointCollector.collect_data_points(
                        _s, user_id, item_id, location_id
                    )

            if len(data_points) < PredictionConfig.MIN_DATA_POINTS_FOR_ML:
                return None

            # Prepare data for regression
            X, y, weights = MLPredictionService._prepare_regression_data(data_points)

            if len(X) == 0:
                return None

            # Perform weighted linear regression
            daily_rate, r_squared = MLPredictionService._weighted_linear_regression(
                X, y, weights
            )

            # Determine trend direction
            trend_direction = MLPredictionService._determine_trend_direction(
                daily_rate, r_squared
            )

            # Calculate date range
            date_range = (data_points[-1].timestamp - data_points[0].timestamp).days

            result = MLPredictionResult(
                daily_usage_rate=daily_rate,
                confidence_score=r_squared,
                data_point_count=len(data_points),
                date_range_days=date_range,
                trend_direction=trend_direction,
            )

            return result

        except Exception as e:  # pragma: no cover - defensive
            logger.error(f"ML prediction error: {e}")
            return None

    @staticmethod
    def _prepare_regression_data(
        data_points: list[DataPoint],
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        Prepare data for weighted linear regression with time decay.

        Args:
            data_points: List of DataPoint objects

        Returns:
            tuple: (X_values, y_values, weights)
        """
        if not data_points:
            return np.array([]), np.array([]), np.array([])

        # Convert to daily usage rates
        X = []  # Days since first data point
        y = []  # Daily usage rate
        weights = []  # Time-based weights

        base_time = data_points[0].timestamp
        latest_time = data_points[-1].timestamp

        for point in data_points:
            if point.days_elapsed > 0:  # Avoid division by zero
                # X: days since baseline
                days_since_start = (point.timestamp - base_time).total_seconds() / 86400
                X.append(days_since_start)

                # Y: daily usage rate (negative = consumption)
                daily_rate = point.quantity_change / point.days_elapsed
                y.append(daily_rate)

                # Weight: more recent data gets higher weight
                days_ago = (latest_time - point.timestamp).total_seconds() / 86400
                weight = PredictionConfig.ML_TIME_DECAY_FACTOR**days_ago
                weights.append(weight)

        return np.array(X), np.array(y), np.array(weights)

    @staticmethod
    def _weighted_linear_regression(
        X: np.ndarray, y: np.ndarray, weights: np.ndarray
    ) -> tuple[float, float]:
        """
        Perform weighted linear regression to find trend.

        Args:
            X: Time values (days)
            y: Usage rates (items/day)
            weights: Data point weights

        Returns:
            tuple: (slope, r_squared)
        """
        if len(X) == 0:
            return 0.0, 0.0

        if len(X) == 1:
            return float(y[0]), 1.0  # Perfect fit for single point

        try:
            # Weighted linear regression: y = mx + b
            # We want the slope (m) as our daily usage rate

            # Calculate weighted means
            w_sum = np.sum(weights)
            x_mean = np.sum(weights * X) / w_sum
            y_mean = np.sum(weights * y) / w_sum

            # Calculate weighted slope and intercept
            numerator = np.sum(weights * (X - x_mean) * (y - y_mean))
            denominator = np.sum(weights * (X - x_mean) ** 2)

            if denominator == 0:
                # All X values are the same
                return float(np.mean(y)), 1.0

            slope = numerator / denominator
            intercept = y_mean - slope * x_mean

            # Calculate R² for weighted regression
            y_pred = slope * X + intercept
            ss_res = np.sum(weights * (y - y_pred) ** 2)
            ss_tot = np.sum(weights * (y - y_mean) ** 2)

            r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0.0
            r_squared = max(0.0, min(1.0, r_squared))  # Clamp to [0, 1]

            # Calculate current daily usage rate at most recent time point
            # Use the regression line to predict usage at the latest time point
            if len(X) > 0:
                latest_time = np.max(X)
                current_rate = (
                    slope * latest_time + intercept
                )  # y = mx + b at latest time
            else:
                current_rate = intercept  # If no time variation, use intercept

            return float(current_rate), float(r_squared)

        except Exception as e:
            logger.error(f"Regression calculation error: {e}")
            return 0.0, 0.0

    @staticmethod
    def _determine_trend_direction(daily_rate: float, confidence: float) -> str:
        """
        Determine trend direction based on daily rate and confidence.

        Args:
            daily_rate: Daily usage rate (negative = consumption)
            confidence: R² confidence score

        Returns:
            Trend direction string
        """
        if confidence < 0.1:
            return "unstable"

        if abs(daily_rate) < 0.01:  # Very small change
            return "stable"
        elif daily_rate < -0.01:  # Decreasing (consumption)
            return "decreasing"
        else:  # Increasing (restocking)
            return "increasing"

    @staticmethod
    def batch_predict_locations(
        db_session: Session, user_id: int, item_id: int, location_ids: list[int]
    ) -> dict[int, MLPredictionResult | None]:
        """
        Batch predict usage rates for multiple locations.

        Args:
            db_session: Database session
            user_id: User ID
            item_id: Item ID
            location_ids: List of location IDs

        Returns:
            Dict mapping location_id to MLPredictionResult (or None)
        """
        results = {}
        for location_id in location_ids:
            results[location_id] = MLPredictionService.predict_usage_rate(
                db_session, user_id, item_id, location_id
            )
        return results
