"""
Data point collection system for admin operations.

Collects trustworthy data points from admin actions (COUNT operations + admin operation deltas)
to build reliable trendlines for ML predictions.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from loguru import logger
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db import get_session
from app.inventory.constants import OperationType
from app.inventory.models import ActionLogs

from .config import PredictionConfig


@dataclass
class DataPoint:
    """Represents a single data point for trend analysis."""

    timestamp: datetime
    quantity_change: float  # Net change in quantity (can be negative)
    location_id: int | None

    item_id: int
    days_elapsed: float  # Days since previous data point


class DataPointCollector:
    """Collects and processes admin operation data points for ML predictions."""

    @staticmethod
    def collect_data_points(
        db_session: Session | None,
        user_id: int,
        item_id: int,
        location_id: int | None = None,
        days_back: int = 365,
    ) -> list[DataPoint]:
        """
        Collect data points from admin operations for trend analysis.

        Algorithm:
        1. Find all admin COUNT operations (these are ground truth)
        2. For each COUNT, calculate net change since previous COUNT
        3. Net change = (COUNT2) - (COUNT1 + sum of admin operations between them)

        Args:
            db_session: Database session
            user_id: User ID
            item_id: Item ID
            location_id: Specific location (None for all locations)
            days_back: How many days back to look

        Returns:
            List of DataPoint objects sorted by timestamp
        """

        def _collect(session: Session) -> list[DataPoint]:
            cutoff_time = datetime.now(UTC) - timedelta(days=days_back)

            # Get all COUNT operations (both admin and guest as ground truth points) using select
            stmt = (
                select(ActionLogs)
                .where(
                    ActionLogs.user_id == user_id,
                    ActionLogs.item_id == item_id,
                    ActionLogs.operation_type == OperationType.count,
                    ActionLogs.time_scanned >= cutoff_time,
                )
                .order_by(ActionLogs.time_scanned.asc())
            )

            if location_id:
                stmt = stmt.where(ActionLogs.to_location_id == location_id)

            count_operations = session.execute(stmt).scalars().all()

            if len(count_operations) < 2:
                return []

            data_points: list[DataPoint] = []

            # Process each pair of consecutive COUNT operations
            for i in range(1, len(count_operations)):
                prev_count = count_operations[i - 1]
                curr_count = count_operations[i]

                # Calculate the net usage between these two counts
                net_change = DataPointCollector._calculate_net_change(
                    session, user_id, item_id, prev_count, curr_count
                )

                if net_change is not None:
                    days_elapsed = (
                        curr_count.time_scanned - prev_count.time_scanned
                    ).total_seconds() / 86400

                    # Skip data points with very small time intervals (< 1 hour) to avoid division by near-zero
                    MIN_HOURS_BETWEEN_COUNTS = 1.0
                    if days_elapsed < (MIN_HOURS_BETWEEN_COUNTS / 24.0):
                        logger.debug(
                            f"Skipping data point with {days_elapsed:.4f} days ({days_elapsed * 24.0:.1f} hours) - too close together"
                        )
                        continue

                    data_point = DataPoint(
                        timestamp=curr_count.time_scanned,
                        quantity_change=net_change,
                        location_id=curr_count.to_location_id,
                        item_id=item_id,
                        days_elapsed=days_elapsed,
                    )
                    data_points.append(data_point)

            return data_points

        try:
            if db_session is not None:
                return _collect(db_session)
            with get_session() as _s:
                return _collect(_s)

        except Exception as e:
            logger.error(f"Error collecting data points: {e}")
            return []

    @staticmethod
    def _calculate_net_change(
        db_session: Session | None,
        user_id: int,
        item_id: int,
        prev_count: ActionLogs,
        curr_count: ActionLogs,
    ) -> float | None:
        """
        Calculate net change between two COUNT operations.

        Formula: net_change = (COUNT2) - (COUNT1 + sum of admin operations between)

        Args:
            db_session: Database session
            user_id: User ID
            item_id: Item ID
            prev_count: Previous COUNT operation
            curr_count: Current COUNT operation

        Returns:
            Net change in quantity (negative means net consumption)
        """

        def _calc(session: Session) -> float | None:
            location_id = curr_count.to_location_id

            # Ensure both counts are for the same location
            if prev_count.to_location_id != location_id:
                return None

            # Get ONLY admin operations (excluding COUNTs) between the two counts at this location
            admin_stmt = select(ActionLogs).where(
                ActionLogs.user_id == user_id,
                ActionLogs.item_id == item_id,
                ActionLogs.admin_action.is_(True),
                ActionLogs.operation_type != OperationType.count,
                ActionLogs.time_scanned > prev_count.time_scanned,
                ActionLogs.time_scanned < curr_count.time_scanned,
                or_(
                    ActionLogs.from_location_id == location_id,
                    ActionLogs.to_location_id == location_id,
                ),
            )

            admin_ops = session.execute(admin_stmt).scalars().all()

            # Calculate net admin operations effect (only RESTOCK, TAKEOUT, TRANSFER)
            admin_net_change = 0
            for op in admin_ops:
                # Calculate effect on this location
                if op.to_location_id == location_id:
                    # Adding to this location
                    admin_net_change += op.quantity_delta
                if op.from_location_id == location_id:
                    # Removing from this location
                    admin_net_change -= op.quantity_delta

            # Calculate expected quantity (prev_count + admin operations)
            expected_quantity = prev_count.quantity_delta + admin_net_change

            # Net change = actual - expected
            net_change = curr_count.quantity_delta - expected_quantity

            return net_change

        try:
            if db_session is not None:
                return _calc(db_session)
            with get_session() as _s:
                return _calc(_s)

        except Exception as e:
            logger.error(f"Error calculating net change: {e}")
            return None

    @staticmethod
    def get_data_summary(
        db_session: Session | None,
        user_id: int,
        item_id: int,
        location_id: int | None = None,
    ) -> dict:
        """
        Get summary statistics about available data points.

        Returns:
            Dict with count, date_range, avg_daily_usage, etc.
        """
        try:
            data_points = DataPointCollector.collect_data_points(
                db_session, user_id, item_id, location_id
            )

            if not data_points:
                return {
                    "data_point_count": 0,
                    "date_range_days": 0,
                    "avg_daily_usage": None,
                    "total_usage": 0,
                    "sufficient_for_ml": False,
                }

            total_usage = sum(dp.quantity_change for dp in data_points)
            total_days = sum(dp.days_elapsed for dp in data_points)
            avg_daily_usage = total_usage / total_days if total_days > 0 else 0

            date_range = (data_points[-1].timestamp - data_points[0].timestamp).days

            sufficient_for_ml = (
                len(data_points) >= PredictionConfig.MIN_DATA_POINTS_FOR_ML
            )

            return {
                "data_point_count": len(data_points),
                "date_range_days": date_range,
                "avg_daily_usage": avg_daily_usage,
                "total_usage": total_usage,
                "sufficient_for_ml": sufficient_for_ml,
                "earliest_data": data_points[0].timestamp,
                "latest_data": data_points[-1].timestamp,
            }

        except Exception as e:
            logger.error(f"Error getting data summary: {e}")
            return {
                "data_point_count": 0,
                "date_range_days": 0,
                "avg_daily_usage": None,
                "total_usage": 0,
                "sufficient_for_ml": False,
            }
