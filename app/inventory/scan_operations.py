import logging

from flask import flash, redirect, render_template, url_for
from flask_login import current_user

from app.auth.models import UserItemLocations, Users
from app.inventory.inventory_ops import InventoryError, inventory_operation
from app.inventory.models import Items, OperationType

logger = logging.getLogger(__name__)


def get_scan_permissions(squad, is_admin=False):
    """
    Get user permissions for scanning operations.

    Args:
        squad: Squad name
        is_admin: If True, always return True for all permissions

    Returns:
        tuple: (user_count_allow, user_restock_allow, user_take_allow)
    """
    if is_admin:
        return True, True, True

    user_count_allow, user_restock_allow, user_take_allow = (
        Users.query.filter_by(display_name=squad)
        .with_entities(Users.user_count_allow, Users.user_restock_allow, Users.user_take_allow)
        .first()
    )
    return user_count_allow, user_restock_allow, user_take_allow


def handle_scan_start(squad, item_id, is_admin=False):
    """
    Handle the scan start logic - decides between direct scan or location selection.

    Args:
        squad: Squad name
        item_id: Item ID to scan
        is_admin: If True, use admin routes and permissions

    Returns:
        Flask response (redirect)
    """
    item = Items.query.filter_by(id=item_id).first() if item_id else None

    if not item:
        logger.warning(f"Scan attempted with invalid item_id: {item_id}")
        flash("Item not found.", "error")
        endpoint = "admin.admin_scan_items" if is_admin else "guest.index"
        return redirect(url_for(endpoint, squad=squad))

    user_count_allow, user_restock_allow, user_take_allow = get_scan_permissions(squad, is_admin)

    locations = UserItemLocations.query.filter_by(user_id=current_user.id)
    from_location = locations.filter_by(user_access_from=True).all()
    to_location = locations.filter_by(user_access_to=True).all()

    # Adjust counts based on permissions
    from_count = len(from_location) + (1 if user_count_allow else 0) + (1 if user_restock_allow else 0)
    to_count = len(to_location) + (1 if user_take_allow else 0)

    if from_count == to_count == 1:
        route_prefix = "admin" if is_admin else "guest"
        return redirect(
            url_for(
                f"{route_prefix}.scan_item",
                squad=squad,
                item_id=item.id,
                from_location_id=from_location[0].id if from_location else None,
                to_location_id=to_location[0].id if to_location else None,
                user_count_allow=user_count_allow,
                user_restock_allow=user_restock_allow,
                user_take_allow=user_take_allow,
            )
        )
    elif len(from_location) == 0:
        flash("No valid locations found to access items. Please add more in the admin panel.", "error")
        endpoint = "admin.admin_scan_items" if is_admin else "guest.index"
        return redirect(url_for(endpoint, squad=squad))
    else:
        route_prefix = "admin" if is_admin else "guest"
        return redirect(
            url_for(
                f"{route_prefix}.scan_locations",
                squad=squad,
                item_id=item.id,
                user_count_allow=user_count_allow,
                user_restock_allow=user_restock_allow,
                user_take_allow=user_take_allow,
            )
        )


def handle_scan_locations_get(squad, item_id, user_count_allow, user_restock_allow, user_take_allow, is_admin=False):
    """
    Handle GET request for scan locations page.

    Args:
        squad: Squad name
        item_id: Item ID
        user_count_allow: Whether user can count
        user_restock_allow: Whether user can restock
        user_take_allow: Whether user can take
        is_admin: If True, pass admin flag to template

    Returns:
        Flask response (render_template)
    """
    item = Items.query.filter_by(id=item_id).first() if item_id else None

    if not item:
        flash("Item not found.", "error")
        endpoint = "admin.admin_scan_items" if is_admin else "guest.index"
        return redirect(url_for(endpoint, squad=squad))

    locations = UserItemLocations.query.filter_by(user_id=current_user.id)

    if is_admin:
        # Admin sees all locations for both from and to
        from_locations = locations.all()
        to_locations = locations.all()
    else:
        # Guest sees only permitted locations
        from_locations = locations.filter_by(user_access_from=True).all()
        to_locations = locations.filter_by(user_access_to=True).all()

    return render_template(
        "scan_locations.html",
        squad=squad,
        item=item,
        from_locations=from_locations,
        to_locations=to_locations,
        user_count_allow=user_count_allow,
        user_restock_allow=user_restock_allow,
        user_take_allow=user_take_allow,
        logo_img=current_user.image,
        admin=is_admin,
    )


def handle_scan_locations_post(squad, form_data, is_admin=False):
    """
    Handle POST request for scan locations page.

    Args:
        squad: Squad name
        form_data: Request form data
        is_admin: If True, use admin routes

    Returns:
        Flask response (redirect)
    """
    item_id = form_data.get("item_id")
    from_location_id = form_data.get("from_location_id")
    to_location_id = form_data.get("to_location_id")
    same_location_error = form_data.get("same_location_error")

    if same_location_error == "1":
        # Determine the specific error message based on the combination
        error_msg = "Invalid location combination selected, please try again."

        flash(error_msg, "error")
        route_prefix = "admin" if is_admin else "guest"
        return redirect(
            url_for(
                f"{route_prefix}.scan_locations",
                squad=squad,
                item_id=item_id,
            )
        )

    route_prefix = "admin" if is_admin else "guest"
    return redirect(
        url_for(
            f"{route_prefix}.scan_item",
            squad=squad,
            item_id=item_id,
            from_location_id=from_location_id,
            to_location_id=to_location_id,
        )
    )


def handle_scan_item_get(
    squad,
    item_id,
    from_location_id,
    to_location_id,
    user_count_allow,
    user_restock_allow,
    user_take_allow,
    is_admin=False,
):
    """
    Handle GET request for scan item page.

    Args:
        squad: Squad name
        item_id: Item ID
        from_location_id: From location ID
        to_location_id: To location ID
        user_count_allow: Whether user can count
        user_restock_allow: Whether user can restock
        user_take_allow: Whether user can take
        is_admin: If True, pass admin flag to template

    Returns:
        Flask response (render_template or redirect)
    """
    item = Items.query.get(item_id)
    if from_location_id in ["-1", "-2"]:
        from_location = int(from_location_id)  # -1 for RESTOCK, -2 for COUNT
    elif from_location_id is not None:
        from_location = UserItemLocations.query.get(from_location_id)
    else:
        from_location = None

    if to_location_id == "-1":
        to_location = -1
    elif to_location_id is not None:
        to_location = UserItemLocations.query.get(to_location_id)
    else:
        to_location = None

    if not item or not from_location:
        flash("Invalid item or locations.", "error")
        endpoint = "admin.admin_scan_items" if is_admin else "guest.index"
        return redirect(url_for(endpoint, squad=squad))

    return render_template(
        "scan_item.html",
        squad=squad,
        item=item,
        from_location=from_location,
        to_location=to_location,
        user_count_allow=user_count_allow,
        user_restock_allow=user_restock_allow,
        user_take_allow=user_take_allow,
        logo_img=current_user.image,
        admin=is_admin,
    )


def handle_scan_item_post(squad, form_data, is_admin=False):
    """
    Handle POST request for scan item page.

    Args:
        squad: Squad name
        form_data: Request form data
        is_admin: If True, use admin routes and mark as admin action

    Returns:
        Flask response (redirect)
    """
    item_id = form_data.get("item_id")
    from_location_id = form_data.get("from_location_id")
    to_location_id = form_data.get("to_location_id")
    counter_value = form_data.get("counter_value")

    item = Items.query.filter_by(id=item_id).first()

    if not item:
        flash("Item not found. Please verify the UPC code and try again.", "error")
        endpoint = "admin.admin_scan_items" if is_admin else "guest.index"
        return redirect(url_for(endpoint, squad=squad))

    # Basic validation - detailed validation happens in inventory_operation
    if not counter_value or not counter_value.isdigit():
        logger.warning(f"Invalid quantity entered by user {current_user.email}: '{counter_value}'")
        flash("Invalid quantity. Please enter a valid number.", "error")
        endpoint = "admin.admin_scan_items" if is_admin else "guest.index"
        return redirect(url_for(endpoint, squad=squad, item_id=item_id))

    # Check that at least one location is specified
    if (not from_location_id or from_location_id == "-1") and (not to_location_id or to_location_id == "-1"):
        flash("Please select a location for this operation.", "error")
        endpoint = "admin.admin_scan_items" if is_admin else "guest.index"
        return redirect(url_for(endpoint, squad=squad, item_id=item_id))

    # Parse location IDs and convert to integers, handling virtual locations
    from_location_id = int(from_location_id) if from_location_id not in ["-1", "-2"] else int(from_location_id)
    to_location_id = int(to_location_id) if to_location_id != "-1" else -1
    counter_value = int(counter_value)

    # Determine operation type based on virtual location IDs
    if from_location_id == -1:  # RESTOCK
        op_type = OperationType.restock
        from_location_id = None  # Set to None for inventory_operation
    elif from_location_id == -2:  # COUNT
        op_type = OperationType.count
        from_location_id = None  # Set to None for inventory_operation
    elif from_location_id > 0 and to_location_id > 0:  # TRANSFER
        op_type = OperationType.transfer
    elif from_location_id > 0 and to_location_id == -1:  # TAKEOUT
        op_type = OperationType.takeout
        to_location_id = None  # Set to None for inventory_operation
    else:
        flash("Invalid operation parameters.", "error")
        endpoint = "admin.admin_scan_items" if is_admin else "guest.index"
        return redirect(url_for(endpoint, squad=squad, item_id=item_id))

    # Use new inventory_operation function
    try:
        updated_quantities, alerts = inventory_operation(
            user_id=current_user.id,
            item_id=item.id,
            quantity=counter_value,
            operation_type=op_type,
            from_location=from_location_id,
            to_location=to_location_id,
            admin_action=is_admin,
        )
        logger.info(f"Inventory operation completed with {len(alerts)} alerts")
    except InventoryError as e:
        flash(str(e), "error")
        endpoint = "admin.admin_scan_items" if is_admin else "guest.index"
        return redirect(url_for(endpoint, squad=squad, item_id=item_id))
    except Exception as e:
        logger.error(f"Unexpected error during inventory operation: {e}")
        flash("System error - please try again", "error")
        endpoint = "admin.admin_scan_items" if is_admin else "guest.index"
        return redirect(url_for(endpoint, squad=squad, item_id=item_id))

    # Create operation-specific success message
    if op_type == OperationType.count:
        flash(f"Successfully set {item.name} quantity to {counter_value}.", "success")
    elif op_type == OperationType.restock:
        flash(f"Successfully restocked {counter_value} {item.name} from supplier.", "success")
    elif op_type == OperationType.takeout:
        flash(f"Successfully removed {counter_value} {item.name} from inventory.", "success")
    else:
        flash(f"Successfully transferred {counter_value} {item.name}.", "success")

    endpoint = "admin.admin_panel" if is_admin else "guest.index"
    return redirect(url_for(endpoint, squad=squad))
