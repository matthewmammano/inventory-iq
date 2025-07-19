from flask import flash, redirect, url_for, render_template
from flask_login import current_user

from app import db
from app.auth.models import UserItemLocations, Users
from app.inventory.models import ActionLogs, Items


def get_scan_permissions(squad, is_admin=False):
    """
    Get user permissions for scanning operations.
    
    Args:
        squad: Squad name
        is_admin: If True, always return True for both permissions
        
    Returns:
        tuple: (user_recount_allow, user_take_allow)
    """
    if is_admin:
        return True, True
    
    user_recount_allow, user_take_allow = (
        Users.query.filter_by(display_name=squad)
        .with_entities(Users.user_recount_allow, Users.user_take_allow)
        .first()
    )
    return user_recount_allow, user_take_allow


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
        flash("Item not found.", "error")
        endpoint = "admin.admin_panel" if is_admin else "guest.index"
        return redirect(url_for(endpoint, squad=squad))

    user_recount_allow, user_take_allow = get_scan_permissions(squad, is_admin)

    locations = UserItemLocations.query.filter_by(user_id=current_user.id)
    from_location = locations.filter_by(user_access_from=True).all()
    to_location = locations.filter_by(user_access_to=True).all()

    # Adjust counts based on permissions
    from_count = len(from_location) + (1 if user_recount_allow else 0)
    to_count = len(to_location) + (1 if user_take_allow else 0)

    if from_count == to_count == 1:
        route_prefix = "admin" if is_admin else "guest"
        return redirect(
            url_for(
                f"{route_prefix}.scan_item",
                squad=squad,
                item_id=item.id,
                from_location_id=from_location[0].id if from_location else (-1 if user_recount_allow else None),
                to_location_id=to_location[0].id if to_location else (-1 if user_take_allow else None),
                user_recount_allow=user_recount_allow,
                user_take_allow=user_take_allow,
            )
        )
    elif len(from_location) == 0:
        flash("No valid locations found to access items. Please add more in the admin panel.", "error")
        endpoint = "admin.admin_panel" if is_admin else "guest.index"
        return redirect(url_for(endpoint, squad=squad))
    else:
        route_prefix = "admin" if is_admin else "guest"
        return redirect(
            url_for(
                f"{route_prefix}.scan_locations",
                squad=squad,
                item_id=item.id,
                user_recount_allow=user_recount_allow,
                user_take_allow=user_take_allow,
            )
        )


def handle_scan_locations_get(squad, item_id, user_recount_allow, user_take_allow, is_admin=False):
    """
    Handle GET request for scan locations page.
    
    Args:
        squad: Squad name
        item_id: Item ID
        user_recount_allow: Whether user can recount
        user_take_allow: Whether user can take
        is_admin: If True, pass admin flag to template
        
    Returns:
        Flask response (render_template)
    """
    item = Items.query.filter_by(id=item_id).first() if item_id else None

    if not item:
        flash("Item not found.", "error")
        endpoint = "admin.admin_panel" if is_admin else "guest.index"
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
        user_recount_allow=user_recount_allow,
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
        flash("You cannot select the same location for both From and To.", "error")
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


def handle_scan_item_get(squad, item_id, from_location_id, to_location_id, user_recount_allow, user_take_allow, is_admin=False):
    """
    Handle GET request for scan item page.
    
    Args:
        squad: Squad name
        item_id: Item ID
        from_location_id: From location ID
        to_location_id: To location ID
        user_recount_allow: Whether user can recount
        user_take_allow: Whether user can take
        is_admin: If True, pass admin flag to template
        
    Returns:
        Flask response (render_template or redirect)
    """
    item = Items.query.get(item_id)
    from_location = -1 if from_location_id == "-1" else UserItemLocations.query.get(from_location_id)
    to_location = -1 if to_location_id == "-1" else UserItemLocations.query.get(to_location_id)

    if not item or not from_location:
        flash("Invalid item or locations.", "error")
        endpoint = "admin.admin_panel" if is_admin else "guest.index"
        return redirect(url_for(endpoint, squad=squad))

    return render_template(
        "scan_item.html",
        squad=squad,
        item=item,
        from_location=from_location,
        to_location=to_location,
        user_recount_allow=user_recount_allow,
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
        flash("Item not found. Please check the UPC code.", "error")
        endpoint = "admin.admin_panel" if is_admin else "guest.index"
        return redirect(url_for(endpoint, squad=squad))

    if not from_location_id or not to_location_id:
        flash("Both from and to locations must be selected.", "error")
        endpoint = "admin.admin_panel" if is_admin else "guest.index"
        return redirect(url_for(endpoint, squad=squad, item_id=item_id))

    if not counter_value or not counter_value.isdigit():
        flash("Invalid counter value. Please enter a valid number.", "error")
        endpoint = "admin.admin_panel" if is_admin else "guest.index"
        return redirect(url_for(endpoint, squad=squad, item_id=item_id))

    from_location_id = int(from_location_id) if from_location_id != "-1" else None
    to_location_id = int(to_location_id) if to_location_id != "-1" else None
    counter_value = int(counter_value)

    action_log = ActionLogs(
        item_id=item.id,
        from_location_id=from_location_id,
        to_location_id=to_location_id,
        quantity_delta=counter_value,
        admin_action=is_admin,  # Mark as admin action if called from admin
        user_id=current_user.id,
    )
    db.session.add(action_log)
    db.session.flush()

    # Process the action and handle quantity updates
    updated_quantities, alerts = action_log.process_action(db.session)

    # TODO RED: handle alerts - send emails for low/high stock notifications

    db.session.commit()

    flash(f"Successfully moved {counter_value} {item.name}.", "success")
    endpoint = "admin.admin_panel" if is_admin else "guest.index"
    return redirect(url_for(endpoint, squad=squad))