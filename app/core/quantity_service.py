"""
Centralized quantity calculation service.

Single source of truth for all inventory quantity calculations.
Used by both inventory operations and prediction systems.
"""

import logging
from typing import Dict, Optional

from app import db
from app.auth.models import UserItemLocations
from app.inventory.models import (
    ActionLogs,
    ItemLocationQuantities,
    Items,
    OperationType,
    get_or_create_item_location_quantity,
)

logger = logging.getLogger(__name__)


class QuantityService:
    """Centralized service for all quantity calculations."""

    @staticmethod
    def get_current_quantity(user_id: int, item_id: int, location_id: Optional[int] = None) -> Dict[int, int]:
        """Get current quantities for an item at location(s)."""
        query = ItemLocationQuantities.query.filter_by(user_id=user_id, item_id=item_id)
        if location_id is not None:
            query = query.filter_by(location_id=location_id)

        quantities = query.all()
        return {qty.location_id: qty.quantity for qty in quantities}

    @staticmethod
    def recalculate_all_quantities(user_id: int) -> None:
        """
        Recalculate quantities for ALL items and ALL locations.

        Single source of truth: For each (item, location) combo, calculate current quantity
        using: Last COUNT + Sum of operations since COUNT

        Args:
            user_id: User ID to recalculate for
        """
        try:
            logger.info(f"Starting quantity recalculation for user {user_id}")

            # Clear existing quantities
            ItemLocationQuantities.query.filter_by(user_id=user_id).delete()
            db.session.flush()

            # Get all items and locations for this user
            items = Items.query.filter_by(user_id=user_id, active=True).all()
            locations = UserItemLocations.query.filter_by(user_id=user_id).all()

            calculated_count = 0

            # Calculate quantity for each (item, location) combination
            for item in items:
                for location in locations:
                    try:
                        current_quantity = QuantityService._calculate_location_quantity(user_id, item.id, location.id)

                        # Only create record if there's any quantity (positive or negative)
                        if current_quantity != 0:
                            qty_record = get_or_create_item_location_quantity(db.session, user_id, item.id, location.id)
                            qty_record.quantity = current_quantity
                            calculated_count += 1

                    except Exception as e:
                        logger.error(f"Failed to calculate quantity for item {item.id}, location {location.id}: {e}")
                        continue

            db.session.commit()
            logger.info(f"Recalculation complete: updated {calculated_count} quantity records")

        except Exception as e:
            db.session.rollback()
            logger.error(f"Quantity recalculation failed for user {user_id}: {e}")
            raise RuntimeError("Failed to recalculate inventory quantities")

    @staticmethod
    def _calculate_location_quantity(user_id: int, item_id: int, location_id: int) -> int:
        """Calculate quantity for a specific (item, location) combination."""
        # Find most recent COUNT for this (item, location)
        last_count = (
            ActionLogs.query.filter_by(
                user_id=user_id,
                item_id=item_id,
                to_location_id=location_id,
                operation_type=OperationType.count,
            )
            .order_by(ActionLogs.time_scanned.desc())
            .first()
        )

        if last_count:
            # Start from COUNT value and add operations since
            current_quantity = last_count.quantity_delta

            operations_since = ActionLogs.query.filter(
                ActionLogs.user_id == user_id,
                ActionLogs.item_id == item_id,
                ActionLogs.time_scanned > last_count.time_scanned,
                ActionLogs.operation_type != OperationType.count,
                (ActionLogs.to_location_id == location_id) | (ActionLogs.from_location_id == location_id),
            ).all()

            for op in operations_since:
                if op.to_location_id == location_id:
                    current_quantity += op.quantity_delta  # Add to location
                if op.from_location_id == location_id:
                    current_quantity -= op.quantity_delta  # Remove from location
        else:
            # No COUNT found - calculate from all operations (start at 0)
            current_quantity = 0

            all_operations = (
                ActionLogs.query.filter(
                    ActionLogs.user_id == user_id,
                    ActionLogs.item_id == item_id,
                    (ActionLogs.to_location_id == location_id) | (ActionLogs.from_location_id == location_id),
                )
                .order_by(ActionLogs.time_scanned.asc())
                .all()
            )

            for op in all_operations:
                if op.operation_type == OperationType.count and op.to_location_id == location_id:
                    current_quantity = op.quantity_delta  # Set absolute
                elif op.to_location_id == location_id:
                    current_quantity += op.quantity_delta  # Add to location
                elif op.from_location_id == location_id:
                    current_quantity -= op.quantity_delta  # Remove from location

        return current_quantity
