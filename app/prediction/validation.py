"""
RESTOCK validation logic to ensure data quality.

Only allows RESTOCK operations when there was a recent COUNT operation
to ensure trustworthy data points for ML predictions.
"""

from datetime import UTC, datetime
from typing import Any

from loguru import logger
from sqlalchemy.orm import Session

from app.inventory.data.action_log_queries import get_recent_admin_count

from .config import PredictionConfig


class RestockValidationError(Exception):
    """Raised when RESTOCK operation validation fails."""


class RestockValidator:
    """Validates RESTOCK operations require recent COUNT operations."""

    @staticmethod
    def validate_restock_operation(
        user_id: int, item_id: int, location_id: int, session: Session | None = None
    ) -> tuple[bool, str | None]:
        """
        Validate that a RESTOCK operation can proceed.

        Args:
            db_session: Database session
            user_id: User performing operation
            item_id: Item being restocked
            location_id: Location of restock
            session: Optional[Session]

        Returns:
            tuple: (is_valid, error_message)

        Raises:
            RestockValidationError: If validation fails with user-friendly message
        """
        try:
            # Check for recent COUNT operation at this location
            recent_count = get_recent_admin_count(
                user_id,
                item_id,
                location_id,
                PredictionConfig.RESTOCK_VALIDATION_HOURS,
                session=session,
            )

            if not recent_count:
                hours = PredictionConfig.RESTOCK_VALIDATION_HOURS
                error_msg = (
                    f"RESTOCK requires a COUNT operation within the past {hours} hours "
                    f"at this location to ensure accurate inventory tracking. "
                    f"Please perform a COUNT first, then try the RESTOCK again."
                )
                logger.warning(
                    f"RESTOCK validation failed: No recent COUNT for user {user_id}, "
                    f"item {item_id}, location {location_id}"
                )
                return False, error_msg

            logger.info(
                f"RESTOCK validation passed: Recent COUNT found at {recent_count.time_scanned} "
                f"for user {user_id}, item {item_id}, location {location_id}"
            )
            return True, None

        except Exception as e:
            logger.error(f"RESTOCK validation error: {e}")
            raise RestockValidationError(
                "System error during RESTOCK validation. Please try again."
            )

    @staticmethod
    def get_validation_status(
        user_id: int, item_id: int, location_id: int, session: Session | None = None
    ) -> dict[str, Any]:
        """
        Get validation status information for UI display.

        Returns:
            dict: Contains validation status, last_count_time, hours_remaining
        """
        try:
            cutoff_time = datetime.now(UTC) - PredictionConfig.RESTOCK_VALIDATION_DELTA

            # Find most recent COUNT at this location
            recent_count = get_recent_admin_count(
                user_id,
                item_id,
                location_id,
                PredictionConfig.RESTOCK_VALIDATION_HOURS,
                session=session,
            )

            if not recent_count:
                return {
                    "is_valid": False,
                    "last_count_time": None,
                    "hours_remaining": 0,
                    "message": "No COUNT operation found. Please perform a COUNT first.",
                }

            is_valid = recent_count.time_scanned >= cutoff_time

            if is_valid:
                hours_since_count = (
                    datetime.now(UTC) - recent_count.time_scanned
                ).total_seconds() / 3600
                hours_remaining = (
                    PredictionConfig.RESTOCK_VALIDATION_HOURS - hours_since_count
                )
            else:
                hours_remaining = 0

            return {
                "is_valid": is_valid,
                "last_count_time": recent_count.time_scanned,
                "hours_remaining": max(0, hours_remaining),
                "message": (
                    "Valid for RESTOCK"
                    if is_valid
                    else "COUNT expired. Please perform a new COUNT."
                ),
            }

        except Exception as e:
            logger.error(f"Error getting validation status: {e}")
            return {
                "is_valid": False,
                "last_count_time": None,
                "hours_remaining": 0,
                "message": "Error checking validation status",
            }
