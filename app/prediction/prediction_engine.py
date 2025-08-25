"""
Main prediction engine that combines ML and Prior predictions with confidence scoring.

Handles decision logic for when to use ML vs Prior vs Combined predictions
based on data availability and confidence thresholds.
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from .aggregation import PriorPredictionResult, PriorTrendlineAggregator
from .config import PredictionConfig
from .ml_service import MLPredictionResult, MLPredictionService

logger = logging.getLogger(__name__)


class PredictionType(Enum):
    """Types of predictions available."""

    ML_ONLY = "ML"
    PRIOR_ONLY = "PRIOR"
    COMBINED = "COMBINED"
    NONE = "NONE"


@dataclass
class CombinedPredictionResult:
    """Combined prediction result with confidence metrics."""

    daily_usage_rate: float  # Final predicted daily usage rate
    confidence_score: float  # Overall confidence (0-1)
    prediction_type: PredictionType  # Which method was used

    # Source predictions
    ml_prediction: Optional[MLPredictionResult] = None
    prior_prediction: Optional[PriorPredictionResult] = None

    # Combination weights (if COMBINED)
    ml_weight: float = 0.0
    prior_weight: float = 0.0

    # Metadata for frontend display
    data_point_count: int = 0
    date_range_days: int = 0
    confidence_explanation: str = ""


class PredictionEngine:
    """Main prediction engine for inventory usage forecasting."""

    @staticmethod
    def predict_usage(
        db_session: Session, user_id: int, item_id: int, location_id: int
    ) -> Optional[CombinedPredictionResult]:
        """
        Predict daily usage rate for item at specific location.

        Decision logic:
        1. Try ML prediction if sufficient data
        2. Try Prior prediction if available
        3. Combine both if both available with good confidence
        4. Return best single prediction if combination not viable
        5. Return None if neither available

        Args:
            db_session: Database session
            user_id: User ID
            item_id: Item ID
            location_id: Location ID

        Returns:
            CombinedPredictionResult or None if no prediction possible
        """
        try:
            # Get ML prediction
            ml_result = MLPredictionService.predict_usage_rate(db_session, user_id, item_id, location_id)

            # Get Prior prediction
            prior_result = PriorTrendlineAggregator.get_prior_prediction(db_session, user_id, item_id, location_id)

            # Decide which prediction method to use
            return PredictionEngine._decide_prediction_method(ml_result, prior_result)

        except Exception as e:
            logger.error(f"Prediction engine error: {e}")
            return None

    @staticmethod
    def _decide_prediction_method(
        ml_result: Optional[MLPredictionResult], prior_result: Optional[PriorPredictionResult]
    ) -> Optional[CombinedPredictionResult]:
        """
        Decide which prediction method to use based on availability and confidence.
        """
        # Case 1: Neither available
        if not ml_result and not prior_result:
            return None

        # Case 2: Only ML available
        if ml_result and not prior_result:
            return PredictionEngine._create_ml_only_result(ml_result)

        # Case 3: Only Prior available
        if prior_result and not ml_result:
            return PredictionEngine._create_prior_only_result(prior_result)

        # Case 4: Both available - decide whether to combine
        if ml_result and prior_result:
            return PredictionEngine._create_combined_result(ml_result, prior_result)

        return None

    @staticmethod
    def _create_ml_only_result(ml_result: MLPredictionResult) -> CombinedPredictionResult:
        """Create result using only ML prediction."""
        confidence_explanation = (
            f"ML prediction from {ml_result.data_point_count} data points "
            f"over {ml_result.date_range_days} days (R²={ml_result.confidence_score:.2f})"
        )

        return CombinedPredictionResult(
            daily_usage_rate=ml_result.daily_usage_rate,
            confidence_score=ml_result.confidence_score,
            prediction_type=PredictionType.ML_ONLY,
            ml_prediction=ml_result,
            ml_weight=1.0,
            data_point_count=ml_result.data_point_count,
            date_range_days=ml_result.date_range_days,
            confidence_explanation=confidence_explanation,
        )

    @staticmethod
    def _create_prior_only_result(prior_result: PriorPredictionResult) -> CombinedPredictionResult:
        """Create result using only Prior prediction."""
        confidence_explanation = PriorTrendlineAggregator.get_confidence_explanation(
            prior_result.confidence_score, prior_result.location_count
        )

        return CombinedPredictionResult(
            daily_usage_rate=prior_result.daily_usage_rate,
            confidence_score=prior_result.confidence_score,
            prediction_type=PredictionType.PRIOR_ONLY,
            prior_prediction=prior_result,
            prior_weight=1.0,
            confidence_explanation=confidence_explanation,
        )

    @staticmethod
    def _create_combined_result(
        ml_result: MLPredictionResult, prior_result: PriorPredictionResult
    ) -> CombinedPredictionResult:
        """Create combined result from both ML and Prior predictions."""

        # Calculate adaptive weights based on confidence scores
        ml_weight, prior_weight = PredictionEngine._calculate_adaptive_weights(
            ml_result.confidence_score, prior_result.confidence_score, ml_result.data_point_count
        )

        # Weighted combination of daily usage rates
        combined_rate = ml_weight * ml_result.daily_usage_rate + prior_weight * prior_result.daily_usage_rate

        # Combined confidence score (weighted average)
        combined_confidence = ml_weight * ml_result.confidence_score + prior_weight * prior_result.confidence_score

        confidence_explanation = (
            f"Combined: {ml_weight:.1%} ML ({ml_result.data_point_count} points, "
            f"R²={ml_result.confidence_score:.2f}) + {prior_weight:.1%} Prior "
            f"({prior_result.location_count} locations)"
        )

        return CombinedPredictionResult(
            daily_usage_rate=combined_rate,
            confidence_score=combined_confidence,
            prediction_type=PredictionType.COMBINED,
            ml_prediction=ml_result,
            prior_prediction=prior_result,
            ml_weight=ml_weight,
            prior_weight=prior_weight,
            data_point_count=ml_result.data_point_count,
            date_range_days=ml_result.date_range_days,
            confidence_explanation=confidence_explanation,
        )

    @staticmethod
    def _calculate_adaptive_weights(
        ml_confidence: float, prior_confidence: float, ml_data_points: int
    ) -> tuple[float, float]:
        """
        Calculate adaptive weights for combining ML and Prior predictions.

        Logic:
        - More ML data points = higher ML weight
        - Higher confidence scores = higher weight for that method
        - Ensure weights sum to 1.0

        Args:
            ml_confidence: ML R² confidence score
            prior_confidence: Prior confidence score
            ml_data_points: Number of ML data points

        Returns:
            tuple: (ml_weight, prior_weight)
        """
        # Base weights from config
        base_ml_weight = PredictionConfig.DEFAULT_ML_WEIGHT
        base_prior_weight = PredictionConfig.DEFAULT_PRIOR_WEIGHT

        # Adjust based on data point count (more data = higher ML weight)
        data_point_factor = min(1.0, ml_data_points / 10.0)  # Cap at 10 points

        # Adjust based on confidence difference
        confidence_ratio = (
            ml_confidence / (ml_confidence + prior_confidence) if (ml_confidence + prior_confidence) > 0 else 0.5
        )

        # Combine factors
        ml_weight = base_ml_weight * (0.5 + 0.3 * data_point_factor + 0.2 * confidence_ratio)
        prior_weight = 1.0 - ml_weight

        # Ensure weights are reasonable
        ml_weight = max(0.1, min(0.9, ml_weight))
        prior_weight = 1.0 - ml_weight

        return ml_weight, prior_weight

    @staticmethod
    def predict_item_total(db_session: Session, user_id: int, item_id: int, location_ids: List[int]) -> Dict:
        """
        Predict total daily usage for an item across all locations.

        Args:
            db_session: Database session
            user_id: User ID
            item_id: Item ID
            location_ids: List of location IDs to include

        Returns:
            Dict with total prediction and per-location breakdown
        """
        try:
            location_predictions = {}
            total_daily_usage = 0.0
            total_confidence = 0.0
            prediction_count = 0

            # Get predictions for each location
            for location_id in location_ids:
                prediction = PredictionEngine.predict_usage(db_session, user_id, item_id, location_id)

                if prediction:
                    location_predictions[location_id] = prediction
                    total_daily_usage += prediction.daily_usage_rate
                    total_confidence += prediction.confidence_score
                    prediction_count += 1
                else:
                    location_predictions[location_id] = None

            # Calculate average confidence
            avg_confidence = total_confidence / prediction_count if prediction_count > 0 else 0.0

            return {
                "total_daily_usage": total_daily_usage,
                "average_confidence": avg_confidence,
                "prediction_count": prediction_count,
                "location_count": len(location_ids),
                "location_predictions": location_predictions,
                "has_predictions": prediction_count > 0,
            }

        except Exception as e:
            logger.error(f"Item total prediction error: {e}")
            return {
                "total_daily_usage": 0.0,
                "average_confidence": 0.0,
                "prediction_count": 0,
                "location_count": len(location_ids),
                "location_predictions": {},
                "has_predictions": False,
            }

    @staticmethod
    def bulk_predict_items(db_session: Session, user_id: int, item_ids: List[int]) -> Dict[int, Dict]:
        """
        Bulk predict usage for multiple items (for admin restock page).

        Args:
            db_session: Database session
            user_id: User ID
            item_ids: List of item IDs

        Returns:
            Dict mapping item_id to prediction results
        """
        try:
            # Get all locations for this user
            from app.auth.models import UserItemLocations

            locations = db_session.query(UserItemLocations).filter_by(user_id=user_id).all()
            location_ids = [loc.id for loc in locations]

            results = {}
            for item_id in item_ids:
                results[item_id] = PredictionEngine.predict_item_total(db_session, user_id, item_id, location_ids)

            return results

        except Exception as e:
            logger.error(f"Bulk prediction error: {e}")
            return {}
