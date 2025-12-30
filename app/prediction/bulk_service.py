"""
Bulk service for restock analysis and batch predictions.

Provides single-call API for admin restock page with recalculation and predictions.
"""

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.inventory.constants import OperationType
from app.inventory.item_queries import list_items_for_user
from app.inventory.models import ActionLogs, Items
from app.inventory.quantity_service import calculate_item_quantities

from .prediction_engine import PredictionEngine


class BulkService:
    """Bulk prediction service for admin interfaces."""

    @staticmethod
    @contextmanager
    def _ensure_session(session: Session | None):
        """
        Context manager for session handling - use provided session or create temporary one.

        Parameters
        ----------
        session : Session | None
            Database session to use, or None to create a temporary one

        Yields
        ------
        Session
            The provided session or a newly created one
        """
        if session is None:
            with get_session() as _s:
                yield _s
        else:
            yield session

    @staticmethod
    def get_restock_analysis(
        db_session: Session, user_id: int, session: Session | None = None
    ) -> list[dict]:
        """
        Single function call for complete restock analysis.

        Steps:
        1. Get all active items
        2. Get bulk predictions for all items
        3. Calculate restock recommendations
        4. Return formatted data for admin restock page

        Args:
            db_session: Database session
            user_id: User ID

        Returns:
            List of restock analysis dicts ready for template rendering
        """
        try:
            logger.info(f"Starting restock analysis for user {user_id}")

            # Step 1: Get all active items
            _s = session or db_session
            items = list(
                list_items_for_user(
                    user_id,
                    include_inactive=False,
                    order_by_last_accessed=True,
                    session=_s,
                )
            )
            item_ids = [item.id for item in items]

            # Step 2: Get bulk predictions
            # Use provided session if present, otherwise fall back to db_session
            _s = session or db_session
            predictions = PredictionEngine.bulk_predict_items(_s, user_id, item_ids)

            # Step 3: Build restock analysis for each item
            restock_data = []
            for item in items:
                try:
                    analysis = BulkService._analyze_item_restock(
                        item, predictions.get(item.id, {}), user_id, _s
                    )
                    restock_data.append(analysis)
                except Exception as item_error:
                    logger.error(
                        f"Failed to analyze item {item.id} ({item.name}): {item_error}"
                    )
                    # Continue with other items instead of failing completely
                    continue

            # Step 4: Sort by priority: days until low (lowest first), order amount (highest first), estimated total (lowest first)
            def sort_key(x):
                days_val = x["days_until_low"]
                order_val = x["order_amount"]
                estimated_val = x["estimated_total"]

                # Convert None/N/A values to appropriate sort values (put at end)
                if days_val is None:
                    days_sort = 999  # N/A goes last
                else:
                    days_sort = float(days_val)

                if order_val is None:
                    order_sort = (
                        -999
                    )  # N/A goes last (negative because we want highest first)
                else:
                    order_sort = -float(
                        order_val
                    )  # Negative for descending order (highest first)

                estimated_sort = float(estimated_val)  # Lowest first

                return (days_sort, order_sort, estimated_sort, x["item"].name)

            try:
                restock_data.sort(key=sort_key)
            except Exception as sort_error:
                logger.error(f"Sorting failed: {sort_error}")
                # Return unsorted data rather than failing

            # Count items by urgency for summary
            urgent_items = sum(
                1
                for item in restock_data
                if item.get("days_until_low") is not None
                and item["days_until_low"] <= 7
            )
            zero_usage_items = sum(
                1 for item in restock_data if item.get("daily_usage_rate", 0) == 0
            )

            logger.info(
                f"Restock analysis complete: {len(restock_data)} items analyzed, "
                f"{urgent_items} urgent (≤7 days), {zero_usage_items} with zero usage"
            )
            return restock_data

        except Exception as e:
            logger.error(f"Restock analysis failed for user {user_id}: {e}")
            raise

    @staticmethod
    def _analyze_item_restock(
        item: Items, prediction: dict, user_id: int, session: Session
    ) -> dict:
        """
        Analyze restock needs for a single item.

        Args:
            item: Items model instance
            prediction: Prediction data from PredictionEngine
            user_id: User ID

        Returns:
            Dict with restock analysis data
        """
        # Get item settings with explicit type conversion
        try:
            min_qty = int(item.min_quantity) if item.min_quantity is not None else 0
            max_qty = int(item.max_quantity) if item.max_quantity is not None else 0
            batch_size = int(item.batch_size) if item.batch_size is not None else 0
            delivery_days = (
                int(item.restock_delivery_days)
                if item.restock_delivery_days is not None
                else 7
            )
        except (ValueError, TypeError) as e:
            logger.warning(f"Type conversion error for item {item.id} settings: {e}")
            # Use safe defaults
            min_qty = 0
            max_qty = 0
            batch_size = 0
            delivery_days = 7

        # Get current quantities
        current_qty_by_location = calculate_item_quantities(session, user_id, item.id)
        current_total = sum(current_qty_by_location.values())

        # Get prediction data
        daily_usage = abs(prediction.get("total_daily_usage", 0.0))
        avg_confidence = prediction.get("average_confidence", 0.0)
        prediction_count = prediction.get("prediction_count", 0)

        # Calculate estimated count based on last COUNT + trend analysis
        estimated_total = BulkService._calculate_estimated_count(
            user_id, item.id, daily_usage
        )

        # Calculate days until low stock using estimated total for forward-looking analysis
        days_until_low = BulkService._calculate_days_until_low(
            estimated_total, min_qty, daily_usage
        )

        # Calculate order amount (ensure days_until_low is properly typed)
        order_amount = BulkService._calculate_order_amount(
            current_total,
            max_qty,
            daily_usage,
            delivery_days,
            batch_size,
            days_until_low,
        )

        # Format confidence information
        prediction_confidence = BulkService._format_confidence_info(
            avg_confidence, prediction_count, prediction.get("location_predictions", {})
        )

        return {
            "item": item,
            "current_total": current_total,
            "estimated_total": estimated_total,
            "min_quantity": min_qty,
            "max_quantity": max_qty,
            "days_until_low": days_until_low,
            "order_amount": order_amount,
            "prediction_confidence": prediction_confidence,
            "daily_usage_rate": daily_usage,
            "monthly_usage_rate": daily_usage * 30,
            "current_qty_by_location": current_qty_by_location,
        }

    @staticmethod
    def _calculate_estimated_count(
        user_id: int, item_id: int, daily_usage: float, session: Session | None = None
    ) -> int:
        """
        Calculate estimated count based on last COUNT + predicted usage since then.

        Logic:
        1. Find most recent COUNT operation for this item across all locations
        2. Calculate days elapsed since that COUNT
        3. Estimate consumption: days_elapsed * daily_usage
        4. Return: last_count_value - estimated_consumption

        Parameters
        ----------
        user_id : int
            User ID
        item_id : int
            Item ID
        daily_usage : float
            Daily usage rate from ML predictions
        session : Session | None, optional
            Database session, by default None (creates temporary session)

        Returns
        -------
        int
            Estimated current count (can be negative if estimated overconsumption)
        """
        with BulkService._ensure_session(session) as s:
            try:
                # Find most recent COUNT operation for this item
                stmt = (
                    select(ActionLogs)
                    .where(
                        ActionLogs.user_id == user_id,
                        ActionLogs.item_id == item_id,
                        ActionLogs.operation_type == OperationType.count,
                    )
                    .order_by(ActionLogs.time_scanned.desc())
                )
                last_count = s.execute(stmt).scalars().first()

                # No COUNT found - fall back to current calculated quantity
                if not last_count:
                    current_qty_by_location = calculate_item_quantities(
                        s, user_id, item_id
                    )
                    return sum(current_qty_by_location.values())

                # Calculate days elapsed since last COUNT
                now = datetime.now(UTC)
                count_time = last_count.time_scanned
                if count_time.tzinfo is None:
                    count_time = count_time.replace(tzinfo=UTC)

                days_elapsed = (now - count_time).total_seconds() / (24 * 3600)
                estimated_consumption = daily_usage * days_elapsed

                # Get total from that COUNT across all locations
                count_total = BulkService._get_count_total_at_time(
                    user_id, item_id, last_count.time_scanned, session=s
                )

                estimated_total = count_total - estimated_consumption
                return int(estimated_total)

            except Exception as e:
                logger.error(
                    f"Error calculating estimated count for item {item_id}: {e}"
                )
                # Fall back to current calculated quantity
                current_qty_by_location = calculate_item_quantities(s, user_id, item_id)
                return sum(current_qty_by_location.values())

    @staticmethod
    def _get_count_total_at_time(
        user_id: int, item_id: int, count_time: datetime, session: Session | None = None
    ) -> int:
        """
        Get total quantity from all COUNT operations at or near the specified time.

        Parameters
        ----------
        user_id : int
            User ID
        item_id : int
            Item ID
        count_time : datetime
            Time of the COUNT operation
        session : Session | None, optional
            Database session, by default None (creates temporary session)

        Returns
        -------
        int
            Total count value across all locations at that time
        """
        try:
            # Handle timezone-aware/naive datetime
            if count_time.tzinfo is None:
                count_time = count_time.replace(tzinfo=UTC)

            # Get all COUNT operations for this item around this time (within 1 hour)
            time_tolerance = 3600  # 1 hour in seconds
            start_time = count_time.replace(microsecond=0) - timedelta(
                seconds=time_tolerance
            )
            end_time = count_time.replace(microsecond=0) + timedelta(
                seconds=time_tolerance
            )

            start_time = count_time.replace(microsecond=0) - timedelta(
                seconds=time_tolerance
            )
            end_time = count_time.replace(microsecond=0) + timedelta(
                seconds=time_tolerance
            )
            stmt = select(ActionLogs).where(
                ActionLogs.user_id == user_id,
                ActionLogs.item_id == item_id,
                ActionLogs.operation_type == OperationType.count,
                ActionLogs.time_scanned >= start_time,
                ActionLogs.time_scanned <= end_time,
            )
            count_operations = list(session.execute(stmt).scalars().all())

            # Sum up all COUNT values from that time period
            total_count = sum(op.quantity_delta for op in count_operations)
            return total_count

        except Exception as e:
            logger.error(f"Error getting count total at time: {e}")
            return 0

    @staticmethod
    def _calculate_days_until_low(
        current_total: int, min_qty: int, daily_usage: float
    ) -> float | None:
        """Calculate days until stock reaches minimum threshold."""
        if daily_usage <= 0:
            return None  # No usage data

        if current_total <= min_qty:
            return 0  # Already at or below minimum

        return (current_total - min_qty) / daily_usage

    @staticmethod
    def _calculate_order_amount(
        current_total: int,
        max_qty: int,
        daily_usage: float,
        delivery_days: int,
        batch_size: int,
        days_until_low: float | None,
    ) -> int | None:
        """Calculate recommended order amount."""
        if max_qty <= 0:
            return 0  # No max quantity set

        if days_until_low is None or not isinstance(days_until_low, (int, float)):
            return None  # Can't calculate without usage data

        # Ensure delivery_days is valid integer
        try:
            delivery_days_num = int(delivery_days) if delivery_days else 7
        except (ValueError, TypeError) as e:
            logger.warning(f"Invalid delivery_days value {delivery_days}: {e}")
            delivery_days_num = 7  # Use default

        # Not urgent if we have more than 2x delivery window
        if days_until_low > delivery_days_num * 2:
            return 0  # Not urgent enough to order

        # Calculate expected usage during delivery period
        delivery_days_num = int(delivery_days) if delivery_days else 7
        expected_usage_during_delivery = daily_usage * delivery_days_num

        # Amount needed to reach max_qty accounting for usage during delivery
        needed = max_qty - current_total + expected_usage_during_delivery

        if needed <= 0:
            return 0

        # Round to batch size if specified
        if batch_size > 0:
            return int(((needed + batch_size - 1) // batch_size) * batch_size)
        else:
            return int(needed)

    @staticmethod
    def _format_confidence_info(
        avg_confidence: float, prediction_count: int, location_predictions: dict
    ) -> dict | None:
        """Format confidence information for frontend display."""
        if avg_confidence <= 0 or prediction_count <= 0:
            return None

        # Count prediction method types
        ml_count = sum(
            1
            for pred in location_predictions.values()
            if pred and pred.prediction_type.value in ["ML", "COMBINED"]
        )
        prior_count = sum(
            1
            for pred in location_predictions.values()
            if pred and pred.prediction_type.value in ["PRIOR", "COMBINED"]
        )

        method_description = (
            f"{ml_count} ML + {prior_count} Prior from {prediction_count} locations"
        )

        return {
            "confidence": avg_confidence,
            "prediction_method": method_description,
            "explanation": f"Average confidence: {avg_confidence:.1%}",
            "ml_locations": ml_count,
            "prior_locations": prior_count,
            "total_locations": prediction_count,
        }
