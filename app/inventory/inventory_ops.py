"""
Production-ready single inventory operation function.
Handles RECOUNT, TRANSFER, and TAKEOUT with first-aid-squad-friendly error handling.
"""

import logging
from datetime import datetime, timezone
from typing import Optional, Tuple, Dict, List

from app import db
from app.inventory.models import ActionLogs, Items
from app.auth.models import UserItemLocations

logger = logging.getLogger(__name__)


class InventoryError(Exception):
    """User-friendly inventory operation errors for first aid squads."""
    pass


def inventory_operation(
    user_id: int,
    item_id: int,
    quantity: int,
    from_location: Optional[int] = None,
    to_location: Optional[int] = None,
    admin_action: bool = False
) -> Tuple[Dict[int, int], List]:
    """
    Single function for ALL inventory operations with bulletproof error handling.
    
    Operation Types (auto-detected):
    - RECOUNT: from_location=None, to_location=X (sets absolute quantity)
    - TRANSFER: from_location=X, to_location=Y (moves quantity between locations)  
    - TAKEOUT: from_location=X, to_location=None (removes quantity from inventory)
    
    Args:
        user_id: User performing operation
        item_id: Item being operated on
        quantity: Amount (positive integer)
        from_location: Source location ID (None for RECOUNT)
        to_location: Destination location ID (None for TAKEOUT)
        admin_action: Whether this is an admin operation
        
    Returns:
        tuple: (updated_quantities_dict, alerts_list)
        
    Raises:
        InventoryError: User-friendly error messages for first aid squads
    """
    try:
        # Validate operation type
        op_type = _detect_operation_type(from_location, to_location)
        
        # Validate inputs
        _validate_inputs(user_id, item_id, quantity, from_location, to_location, op_type)
        
        # Update item last_accessed timestamp
        item = Items.query.filter_by(id=item_id, user_id=user_id).first()
        item.last_accessed = datetime.now(timezone.utc)
        
        # Create and process action
        action_log = _create_action_log(user_id, item_id, quantity, from_location, to_location, admin_action)
        updated_quantities, alerts = _process_action_safely(action_log)
        
        # Handle alerts (non-blocking)
        _handle_alerts_safely(alerts, user_id, op_type)
        
        # Commit transaction
        db.session.commit()
        logger.info(f"{op_type} completed: item {item_id}, quantity {quantity}")
        
        return updated_quantities, alerts
        
    except InventoryError:
        db.session.rollback()
        raise  # Re-raise user-friendly errors as-is
    except Exception as e:
        db.session.rollback()
        logger.error(f"Unexpected inventory operation error: {e}")
        raise InventoryError("System error - please try again or contact support")


def _detect_operation_type(from_location: Optional[int], to_location: Optional[int]) -> str:
    """Detect operation type from location parameters."""
    if from_location is None and to_location is not None:
        return "RECOUNT"
    elif from_location is not None and to_location is not None:
        return "TRANSFER"
    elif from_location is not None and to_location is None:
        return "TAKEOUT"
    else:
        raise InventoryError("Invalid operation - must specify either from_location, to_location, or both")


def _validate_inputs(user_id: int, item_id: int, quantity: int, 
                    from_location: Optional[int], to_location: Optional[int], op_type: str):
    """Validate all inputs with first-aid-squad-friendly error messages."""
    
    # Validate quantity
    if not isinstance(quantity, int) or quantity < 0:
        raise InventoryError("Quantity must be a positive number")
    
    if op_type in ["TRANSFER", "TAKEOUT"] and quantity == 0:
        raise InventoryError("Cannot transfer or remove zero items")
        
    # Validate item exists
    item = Items.query.filter_by(id=item_id, user_id=user_id).first()
    if not item:
        raise InventoryError("Item not found in your inventory")
        
    # Validate locations exist
    if from_location is not None:
        from_loc = UserItemLocations.query.filter_by(id=from_location, user_id=user_id).first()
        if not from_loc:
            raise InventoryError("Source location not found")
            
    if to_location is not None:
        to_loc = UserItemLocations.query.filter_by(id=to_location, user_id=user_id).first()
        if not to_loc:
            raise InventoryError("Destination location not found")
            
    # Validate transfer logic
    if op_type == "TRANSFER" and from_location == to_location:
        raise InventoryError("Cannot transfer items to the same location")


def _create_action_log(user_id: int, item_id: int, quantity: int,
                      from_location: Optional[int], to_location: Optional[int], 
                      admin_action: bool) -> ActionLogs:
    """Create ActionLog entry."""
    action_log = ActionLogs(
        user_id=user_id,
        item_id=item_id,
        from_location_id=from_location,
        to_location_id=to_location,
        quantity_delta=quantity,
        admin_action=admin_action,
        time_scanned=datetime.now(timezone.utc)
    )
    
    db.session.add(action_log)
    db.session.flush()  # Get ID but don't commit yet
    return action_log


def _process_action_safely(action_log: ActionLogs) -> Tuple[Dict[int, int], List]:
    """Process action with error handling."""
    try:
        return action_log.process_action(db.session)
    except Exception as e:
        logger.error(f"Failed to process inventory action: {e}")
        raise InventoryError("Failed to update inventory - please try again")


def _handle_alerts_safely(alerts: List, user_id: int, op_type: str):
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


def get_current_quantity(user_id: int, item_id: int, location_id: Optional[int] = None) -> Dict[int, int]:
    """Get current quantities for an item at location(s)."""
    from app.inventory.models import ItemLocationQuantities
    
    query = ItemLocationQuantities.query.filter_by(user_id=user_id, item_id=item_id)
    if location_id is not None:
        query = query.filter_by(location_id=location_id)
        
    quantities = query.all()
    return {qty.location_id: qty.quantity for qty in quantities}