"""
Prior trendline aggregation logic for combining location-based usage patterns.

Handles aggregation of prior daily usage across multiple locations for an item,
treating each location as equal contributor to overall item usage.
"""

from dataclasses import dataclass

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import UserItemLocations
from app.db import get_session
from app.inventory.data.item_queries import get_item
from app.inventory.data.models import Items
from app.inventory.data.quantity import calculate_item_quantities


@dataclass
class PriorPredictionResult:
    """Result from prior knowledge prediction."""

    daily_usage_rate: float  # Items per day from prior knowledge
    confidence_score: float  # Confidence based on data completeness (0-1)
    location_count: int  # Number of locations contributing
    source_locations: list[int]  # Location IDs that contributed
    prediction_type: str = "PRIOR"


class PriorTrendlineAggregator:
    """Aggregates prior daily usage knowledge across item locations."""

    @staticmethod
    def get_prior_prediction(
        db_session: Session | None,
        user_id: int,
        item_id: int,
        location_id: int | None = None,
    ) -> PriorPredictionResult | None:
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
            # Normalise session handling: prefer Session.get for primary-key lookups
            if db_session is None:
                with get_session() as _s:
                    item = _s.get(Items, item_id)
                    if (
                        not item
                        or item.user_id != user_id
                        or item.prior_daily_usage is None
                    ):
                        return None

                    if location_id is not None:
                        return PriorTrendlineAggregator._single_location_prediction(
                            _s, user_id, item, location_id
                        )
                    return PriorTrendlineAggregator._aggregated_prediction(
                        _s, user_id, item
                    )
            else:
                item = get_item(item_id, session=db_session)
                if (
                    not item
                    or item.user_id != user_id
                    or item.prior_daily_usage is None
                ):
                    return None

                if location_id is not None:
                    return PriorTrendlineAggregator._single_location_prediction(
                        db_session, user_id, item, location_id
                    )
                return PriorTrendlineAggregator._aggregated_prediction(
                    db_session, user_id, item
                )

        except Exception as e:
            logger.error(f"Prior prediction error: {e}")
            return None

    @staticmethod
    def _single_location_prediction(
        db_session: Session, user_id: int, item: Items, location_id: int
    ) -> PriorPredictionResult | None:
        """
        Calculate prior prediction for a single location.

        Logic: Distribute total item usage equally across all active locations.
        """
        try:
            # Get all locations that have this item
            locations = PriorTrendlineAggregator._get_active_locations(
                db_session, user_id, item.id
            )

            if not locations:
                return None

            # Check if requested location is in active locations
            if location_id not in [loc.id for loc in locations]:
                return None

            # Distribute total usage equally across locations
            location_count = len(locations)
            prior_usage = float(
                item.prior_daily_usage if item.prior_daily_usage is not None else 0.0
            )
            daily_usage_per_location = prior_usage / location_count

            # Confidence based on data concentration
            # More locations = lower confidence due to distribution uncertainty
            confidence = max(0.1, min(1.0, 1.0 / max(1, location_count * 0.5)))

            return PriorPredictionResult(
                daily_usage_rate=-abs(
                    daily_usage_per_location
                ),  # Negative = consumption
                confidence_score=confidence,
                location_count=location_count,
                source_locations=[location_id],
            )

        except Exception as e:
            logger.error(f"Single location prior prediction error: {e}")
            return None

    @staticmethod
    def _aggregated_prediction(
        db_session: Session, user_id: int, item: Items
    ) -> PriorPredictionResult | None:
        """
        Calculate aggregated prior prediction across all locations.
        """
        try:
            # Get all locations that have this item
            locations = PriorTrendlineAggregator._get_active_locations(
                db_session, user_id, item.id
            )

            if not locations:
                return None

            # Total usage is just the prior daily usage
            total_daily_usage = float(
                item.prior_daily_usage if item.prior_daily_usage is not None else 0.0
            )

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
    def _get_active_locations(
        db_session: Session, user_id: int, item_id: int
    ) -> list[UserItemLocations]:
        """
        Get locations that have had activity for this item.

        Returns:
            List of UserItemLocations that have inventory for this item
        """
        try:
            qty_by_location = calculate_item_quantities(db_session, user_id, item_id)
            active_location_ids = [
                loc_id for loc_id, qty in qty_by_location.items() if qty >= 0
            ]

            if not active_location_ids:
                return []

            stmt = (
                select(UserItemLocations)
                .where(UserItemLocations.user_id == user_id)
                .where(UserItemLocations.id.in_(active_location_ids))
            )

            return list(db_session.execute(stmt).scalars().all())

        except Exception as e:
            logger.error(f"Error getting active locations: {e}")
            return []

    @staticmethod
    def batch_predict_locations(
        db_session: Session, user_id: int, item_id: int, location_ids: list[int]
    ) -> dict[int, PriorPredictionResult | None]:
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
