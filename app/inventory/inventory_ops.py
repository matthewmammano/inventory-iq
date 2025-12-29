"""
Production-ready single inventory operation function.
Handles RECOUNT, TRANSFER, and TAKEOUT with first-aid-squad-friendly error handling.
"""

from datetime import UTC, datetime

from sqlalchemy import select

from app.auth.models import UserItemLocations
from app.db import get_session
from app.inventory.models import ActionLogs, Items, OperationType

from loguru import logger


class InventoryError(Exception):
    """User-friendly inventory operation errors for first aid squads."""


def inventory_operation(
    user_id: int,
    item_id: int,
    quantity: int,
    operation_type: OperationType,
    from_location: int | None = None,
    to_location: int | None = None,
    admin_action: bool = False,
) -> tuple[dict[int, int], list]:
    """
    Single function for ALL inventory operations with bulletproof error handling.

    Operation Types:
    - COUNT: from_location=None, to_location=X (sets absolute quantity)
    - RESTOCK: from_location=None, to_location=X (adds from external supplier)
    - TRANSFER: from_location=X, to_location=Y (moves quantity between locations)
    - TAKEOUT: from_location=X, to_location=None (removes quantity from inventory)

    Args:
        user_id: User performing operation
        item_id: Item being operated on
        quantity: Amount (positive integer)
        operation_type: Type of operation to perform
        from_location: Source location ID (None for COUNT/RESTOCK)
        to_location: Destination location ID (None for TAKEOUT)
        admin_action: Whether this is an admin operation

    Returns:
        tuple: (updated_quantities_dict, alerts_list)

    Raises:
        InventoryError: User-friendly error messages for first aid squads
    """
    try:
        with get_session() as session:
            # Validate inputs (may need DB access for validators)
            _validate_inputs(
                session,
                user_id,
                item_id,
                quantity,
                operation_type,
                from_location,
                to_location,
            )

            # Update item last_accessed timestamp
            stmt_item = select(Items).where(
                Items.id == item_id, Items.user_id == user_id
            )
            item = session.execute(stmt_item).scalars().first()
            if item:
                item.last_accessed = datetime.now(UTC)

            # Create and process action
            action_log = _create_action_log(
                session,
                user_id,
                item_id,
                quantity,
                operation_type,
                from_location,
                to_location,
                admin_action,
            )
            updated_quantities, alerts = _process_action_safely(action_log, session)

            # Commit transaction BEFORE alert processing to ensure inventory state is persisted
            # This prevents partial state if alert processing fails
            session.commit()
            logger.info(
                f"{operation_type.value} completed: item {item_id}, quantity {quantity}"
            )

            # Handle alerts (non-blocking) - after inventory commit
            _handle_alerts_safely(alerts, user_id, operation_type.value)

            return updated_quantities, alerts

    except InventoryError:
        # Re-raise user-friendly errors as-is
        raise
    except Exception as e:
        logger.error(f"Unexpected inventory operation error: {e}")
        raise InventoryError("System error - please try again or contact support")


def _validate_inputs(
    session,
    user_id: int,
    item_id: int,
    quantity: int,
    operation_type: OperationType,
    from_location: int | None,
    to_location: int | None,
):
    """Validate all inputs with first-aid-squad-friendly error messages."""

    # Validate quantity
    if not isinstance(quantity, int) or quantity < 0:
        raise InventoryError("Quantity must be a positive number")

    if (
        operation_type in [OperationType.transfer, OperationType.takeout]
        and quantity == 0
    ):
        raise InventoryError("Cannot transfer or remove zero items")

    # Validate operation type matches location parameters
    if operation_type == OperationType.count:
        if from_location is not None or to_location is None:
            raise InventoryError("COUNT requires no from_location and a to_location")
    elif operation_type == OperationType.restock:
        if from_location is not None or to_location is None:
            raise InventoryError("RESTOCK requires no from_location and a to_location")

        # RESTOCK validation - require recent COUNT operation
        from app.prediction.validation import RestockValidator

        # validate_restock_operation expects (user_id, item_id, location_id, session=None)
        # to_location was checked above and is not None here
        is_valid, error_msg = RestockValidator.validate_restock_operation(
            user_id, item_id, to_location, session
        )
        if not is_valid:
            raise InventoryError(error_msg)

    elif operation_type == OperationType.transfer:
        if from_location is None or to_location is None:
            raise InventoryError("TRANSFER requires both from_location and to_location")
        if from_location == to_location:
            raise InventoryError("Cannot transfer items to the same location")
    elif operation_type == OperationType.takeout:
        if from_location is None or to_location is not None:
            raise InventoryError("TAKEOUT requires from_location and no to_location")

    # Validate item exists
    stmt_item = select(Items).where(Items.id == item_id, Items.user_id == user_id)
    item = session.execute(stmt_item).scalars().first()
    if not item:
        raise InventoryError("Item not found in your inventory")

    # Validate locations exist
    if from_location is not None:
        stmt_from = select(UserItemLocations).where(
            UserItemLocations.id == from_location, UserItemLocations.user_id == user_id
        )
        from_loc = session.execute(stmt_from).scalars().first()
        if not from_loc:
            raise InventoryError("Source location not found")

    if to_location is not None:
        stmt_to = select(UserItemLocations).where(
            UserItemLocations.id == to_location, UserItemLocations.user_id == user_id
        )
        to_loc = session.execute(stmt_to).scalars().first()
        if not to_loc:
            raise InventoryError("Destination location not found")


def _create_action_log(
    session,
    user_id: int,
    item_id: int,
    quantity: int,
    operation_type: OperationType,
    from_location: int | None,
    to_location: int | None,
    admin_action: bool,
) -> ActionLogs:
    """Create ActionLog entry with automatic restock detection."""
    action_log = ActionLogs(
        user_id=user_id,
        item_id=item_id,
        operation_type=operation_type,
        from_location_id=from_location,
        to_location_id=to_location,
        quantity_delta=quantity,
        admin_action=admin_action,
        time_scanned=datetime.now(UTC),
    )

    session.add(action_log)
    session.flush()  # Get ID but don't commit yet

    # Admin actions are now properly typed with explicit operation_type

    return action_log


def _process_action_safely(
    action_log: ActionLogs, session
) -> tuple[dict[int, int], list]:
    """Process action with error handling."""
    try:
        return action_log.process_action(session)
    except Exception as e:
        logger.error(f"Failed to process inventory action: {e}")
        raise InventoryError("Failed to update inventory - please try again")


def _handle_alerts_safely(alerts: list, user_id: int, op_type: str):
    """Handle alerts without failing the main operation."""
    if not alerts:
        return

    try:
        from app.alerts.alert_service import AlertQueueService

        logger.info(f"Processing {len(alerts)} alerts from {op_type}")
        AlertQueueService.queue_alerts_for_user(alerts, user_id)
    except Exception as e:
        # Log error but don't fail the inventory operation
        logger.error(f"Alert processing failed for {op_type}: {e}")
