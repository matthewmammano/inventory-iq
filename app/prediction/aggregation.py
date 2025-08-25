"""
Prior trendline aggregation logic for combining location-based usage patterns.

Handles aggregation of prior daily usage across multiple locations for an item,
treating each location as equal contributor to overall item usage.
"""

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.auth.models import UserItemLocations
from app.inventory.models import Items

logger = logging.getLogger(__name__)


@dataclass
class PriorPredictionResult:
    """Result from prior knowledge prediction."""

    daily_usage_rate: float  # Items per day from prior knowledge
    confidence_score: float  # Confidence based on data completeness (0-1)
    location_count: int  # Number of locations contributing
    source_locations: List[int]  # Location IDs that contributed
    prediction_type: str = "PRIOR"


class PriorTrendlineAggregator:
    """Aggregates prior daily usage knowledge across item locations."""

    @staticmethod
    def get_prior_prediction(
        db_session: Session, user_id: int, item_id: int, location_id: Optional[int] = None
    ) -> Optional[PriorPredictionResult]:
        """
        Get prior knowledge prediction for an item at specific location or aggregated.

        Args:
            db_session: Database session
            user_id: User ID
            item_id: Item ID
            location_id: Specific location (None for aggregated across all locations)

        Returns:
            PriorPredictionResult if prior knowledge available, None otherwise
        """
        try:
            # Get item with prior daily usage
            item = db_session.query(Items).filter_by(id=item_id, user_id=user_id).first()

            if not item or item.prior_daily_usage is None:
                return None

            if location_id is not None:
                # Single location prediction
                return PriorTrendlineAggregator._single_location_prediction(db_session, user_id, item, location_id)
            else:
                # Aggregated prediction across all locations
                return PriorTrendlineAggregator._aggregated_prediction(db_session, user_id, item)

        except Exception as e:
            logger.error(f"Prior prediction error: {e}")
            return None

    @staticmethod
    def _single_location_prediction(
        db_session: Session, user_id: int, item: Items, location_id: int
    ) -> Optional[PriorPredictionResult]:
        """
        Calculate prior prediction for a single location.

        Logic: Distribute total item usage equally across all active locations.
        """
        try:
            # Get all locations that have this item
            locations = PriorTrendlineAggregator._get_active_locations(db_session, user_id, item.id)

            if not locations:
                return None

            # Check if requested location is in active locations
            if location_id not in [loc.id for loc in locations]:
                return None

            # Distribute total usage equally across locations
            location_count = len(locations)
            daily_usage_per_location = item.prior_daily_usage / location_count

            # Confidence based on data concentration
            # More locations = lower confidence due to distribution uncertainty
            confidence = max(0.1, min(1.0, 1.0 / max(1, location_count * 0.5)))

            return PriorPredictionResult(
                daily_usage_rate=-abs(daily_usage_per_location),  # Negative = consumption
                confidence_score=confidence,
                location_count=location_count,
                source_locations=[location_id],
            )

        except Exception as e:
            logger.error(f"Single location prior prediction error: {e}")
            return None

    @staticmethod
    def _aggregated_prediction(db_session: Session, user_id: int, item: Items) -> Optional[PriorPredictionResult]:
        """
        Calculate aggregated prior prediction across all locations.
        """
        try:
            # Get all locations that have this item
            locations = PriorTrendlineAggregator._get_active_locations(db_session, user_id, item.id)

            if not locations:
                return None

            # Total usage is just the prior daily usage
            total_daily_usage = item.prior_daily_usage

            # High confidence for aggregated predictions
            confidence = 0.9

            return PriorPredictionResult(
                daily_usage_rate=-abs(total_daily_usage),  # Negative = consumption
                confidence_score=confidence,
                location_count=len(locations),
                source_locations=[loc.id for loc in locations],
            )

        except Exception as e:
            logger.error(f"Aggregated prior prediction error: {e}")
            return None

    @staticmethod
    def _get_active_locations(db_session: Session, user_id: int, item_id: int) -> List:
        """
        Get locations that have had activity for this item.

        Returns:
            List of UserItemLocations that have inventory for this item
        """
        try:
            from app.inventory.models import ItemLocationQuantities

            # Get locations with current inventory or recent activity
            active_locations = (
                db_session.query(UserItemLocations)
                .join(ItemLocationQuantities, ItemLocationQuantities.location_id == UserItemLocations.id)
                .filter(
                    UserItemLocations.user_id == user_id,
                    ItemLocationQuantities.item_id == item_id,
                    ItemLocationQuantities.quantity >= 0,  # Include zero quantities (recent activity)
                )
                .distinct()
                .all()
            )

            return active_locations

        except Exception as e:
            logger.error(f"Error getting active locations: {e}")
            return []

    @staticmethod
    def batch_predict_locations(
        db_session: Session, user_id: int, item_id: int, location_ids: List[int]
    ) -> Dict[int, Optional[PriorPredictionResult]]:
        """
        Batch predict prior usage for multiple locations.

        Args:
            db_session: Database session
            user_id: User ID
            item_id: Item ID
            location_ids: List of location IDs

        Returns:
            Dict mapping location_id to PriorPredictionResult (or None)
        """
        results = {}
        for location_id in location_ids:
            results[location_id] = PriorTrendlineAggregator.get_prior_prediction(
                db_session, user_id, item_id, location_id
            )
        return results

    @staticmethod
    def get_confidence_explanation(confidence: float, location_count: int) -> str:
        """
        Get human-readable explanation of confidence score.

        Args:
            confidence: Confidence score (0-1)
            location_count: Number of locations

        Returns:
            Human-readable confidence explanation
        """
        if confidence >= 0.8:
            return f"High confidence - usage distributed across {location_count} location(s)"
        elif confidence >= 0.5:
            return f"Medium confidence - estimated from {location_count} location(s)"
        else:
            return f"Low confidence - usage spread across {location_count} location(s)"
