import json
import os
from datetime import datetime, timezone

from dotenv import load_dotenv
from flask import flash, redirect, render_template, request, session, url_for
from flask_login import current_user

from app import db
from app.auth.models import UserItemLocations, UserItemTags, Users
from app.inventory import admin_bp as bp
from app.inventory.models import ActionLogs, ItemLocationQuantities, Items
from app.inventory.scan_helpers import (
    handle_scan_item_get,
    handle_scan_item_post,
    handle_scan_locations_get,
    handle_scan_locations_post,
    handle_scan_start,
)

load_dotenv()

ADMIN_TIMEOUT_SECONDS = 21600  # 6 hours


@bp.before_request
def check_admin_authorization():
    """
    Secure all admin routes with the following checks:
    1. User must be logged in (Flask-Login)
    2. Admin session must be valid
    3. Squad parameter must be valid
    """
    # Skip if it's a static asset or similar
    if request.endpoint and "static" in request.endpoint:
        return

    # Check if user is logged in
    if not current_user.is_authenticated:
        flash("You must be logged in to access this page.", "warning")
        return redirect(url_for("auth.login"))

    # Get squad parameter
    squad = request.view_args.get("squad")
    if not squad:
        flash("Squad name is required.", "warning")
        return redirect(url_for("auth.login"))

    # Verify the squad exists in the database
    user = Users.query.filter_by(display_name=squad).first()
    if user is None:
        flash("Invalid squad name. Please try again.")
        return redirect(url_for("auth.login"))

    if user.active is False:
        flash("This squad is now inactive. Please contact support.")
        return redirect(url_for("auth.login"))

    # Check admin session validity
    if session.get("admin"):
        now = datetime.now(timezone.utc).timestamp()
        admin_last_active = session.get("admin_last_active")

        if not admin_last_active or now - admin_last_active > ADMIN_TIMEOUT_SECONDS:
            session.pop("admin", None)
            session.pop("admin_last_active", None)
            flash("Admin session expired. Please log in with your PIN again.", "warning")
            return redirect(url_for("guest.index", squad=squad))

        # Update last active timestamp
        session["admin_last_active"] = now
    else:
        session.pop("admin", None)
        session.pop("admin_last_active", None)
        flash("Admin session not found. Please log in with PIN.", "warning")
        return redirect(url_for("guest.index", squad=squad))

    # Verify the current user belongs to the requested squad
    if current_user.display_name != squad:
        flash("You do not have permission to access this squad.", "warning")
        return redirect(url_for("auth.login"))


# Admin dashboard (protected)
@bp.route("/<squad>/admin-panel")
def admin_panel(squad):
    return render_template("admin_panel.html", squad=squad, admin=True)


@bp.route("/<squad>/admin-panel/views")
def admin_panel_views(squad):
    return render_template("admin_panel_views.html", squad=squad, admin=True)


# Admin item viewing page (protected)
@bp.route("/<squad>/admin-panel/view-items")
def admin_view_items(squad):
    items = Items.query.filter_by(user_id=current_user.id).order_by(Items.name).all()
    tags = UserItemTags.query.filter_by(user_id=current_user.id).all()
    return render_template("admin_view_items.html", squad=squad, items=items, tags=tags, admin=True)


# Admin help page (protected)
@bp.route("/<squad>/help")
def help_page(squad):
    developer_phone = os.getenv("CONTACT_PHONE", "UNAVAILABLE")
    return render_template("admin_help.html", squad=squad, contact_phone=developer_phone, admin=True)


# Admin edit items in table page (protected)
@bp.route("/<squad>/admin-panel/edit-items", methods=["GET", "POST"])
def save_items(squad):
    if request.method == "GET":
        items = Items.query.filter_by(user_id=current_user.id).order_by(Items.name).all()
        return render_template(
            "admin_edit_items.html",
            squad=squad,
            items=items,
            tags=UserItemTags.query.filter_by(user_id=current_user.id).all(),
            admin=True,
        )

    # Process the JSON data from the form
    items_data = request.form.get("itemsData")
    if not items_data:
        flash("No item data received", "warning")
        return redirect(url_for("admin.admin_view_items", squad=squad))

    try:
        items_list = json.loads(items_data)
    except json.JSONDecodeError:
        flash("Invalid item data format", "warning")
        return redirect(url_for("admin.admin_view_items", squad=squad))

    # Keep track of existing items to detect deletions
    existing_ids = set(item.id for item in Items.query.filter_by(user_id=current_user.id).all())
    processed_ids = set()
    new_items = []
    error_items = []

    # Process each item
    for item_data in items_list:
        name = item_data.get("name", "").strip()
        if not name:
            error_items.append("Unnamed Item")
            continue

        # Get other fields
        item_id = item_data.get("id")
        active = item_data.get("active", True)  # Default to True if not provided
        tag_ids = item_data.get("tag_ids", [])
        if isinstance(tag_ids, str):
            tag_ids = [int(x.strip()) for x in tag_ids.split(",") if x.strip().isdigit()]
        increments = item_data.get("increments")
        image = item_data.get("image", "").strip()

        # Validate tag_ids if provided
        if tag_ids:
            try:
                valid_tags = UserItemTags.query.filter(
                    UserItemTags.id.in_(tag_ids), UserItemTags.user_id == current_user.id
                ).all()
                if len(valid_tags) != len(tag_ids):
                    error_items.append(name)
                    continue
            except (ValueError, TypeError):
                error_items.append(name)
                continue

        # Process existing items vs new items
        if item_id != "new" and item_id is not None:
            try:
                item_id = int(item_id)
                processed_ids.add(item_id)

                # Update existing item
                item = Items.query.filter_by(id=item_id, user_id=current_user.id).first()
                if not item:
                    error_items.append(name)
                    continue

                item.name = name
                item.active = active
                item.tag_ids = tag_ids
                item.increments = increments if increments else None
                item.image = image if image else None
            except (ValueError, TypeError):
                error_items.append(name)
                continue
        else:
            # Create new item
            try:
                item = Items(
                    active=active,
                    tag_ids=tag_ids,
                    increments=increments if increments else None,
                    name=name,
                    image=image if image else None,
                    user_id=current_user.id,
                )
                db.session.add(item)
                new_items.append(item)
            except Exception:
                error_items.append(name)
                continue

    # Delete items that were removed from the form
    for item_id in existing_ids - processed_ids:
        item_to_delete = Items.query.filter_by(id=item_id, user_id=current_user.id).first()
        if item_to_delete:
            db.session.delete(item_to_delete)

    # Commit all changes
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        flash("Database error occurred. Please try again.", "error")

    if error_items:
        flash(
            f"Some items were not saved due to invalid data: {', '.join(error_items)}",
            "warning",
        )
    else:
        flash("All items saved successfully!", "success")

    return redirect(url_for("admin.admin_view_items", squad=squad))


@bp.route("/<squad>/admin-panel/inventory-count-levels")
def inventory_counts(squad):
    """Display items and their counts across all locations"""
    # Get all items for this user
    items = Items.query.filter_by(user_id=current_user.id, active=True).order_by(Items.name).all()

    # Get all locations for this user
    locations = UserItemLocations.query.filter_by(user_id=current_user.id).order_by(UserItemLocations.name).all()

    # Get all quantity data for this user
    quantities = ItemLocationQuantities.query.filter_by(user_id=current_user.id).all()

    # Create a lookup dictionary for quantities
    qty_lookup = {}
    for qty in quantities:
        key = (qty.item_id, qty.location_id)
        qty_lookup[key] = qty.quantity

    # Build the data structure for the template
    inventory_data = []
    for item in items:
        row_data = {"item": item, "location_counts": {}, "total": 0}

        for location in locations:
            count = qty_lookup.get((item.id, location.id), 0)
            row_data["location_counts"][location.id] = count
            row_data["total"] += count

        inventory_data.append(row_data)

    return render_template(
        "admin_inventory_counts.html", squad=squad, inventory_data=inventory_data, locations=locations, admin=True
    )


@bp.route("/<squad>/admin-panel/restock")
def restock(squad):
    """Display items that need restocking with calculated order amounts"""
    # Get all items for this user with min/max quantities
    items = Items.query.filter_by(user_id=current_user.id, active=True).all()

    # Get all quantity data for this user
    quantities = ItemLocationQuantities.query.filter_by(user_id=current_user.id).all()

    # Create a lookup dictionary for total quantities per item
    item_totals = {}
    for qty in quantities:
        if qty.item_id not in item_totals:
            item_totals[qty.item_id] = 0
        item_totals[qty.item_id] += qty.quantity

    # Calculate restock recommendations
    restock_data = []
    for item in items:
        current_total = item_totals.get(item.id, 0)
        min_qty = item.min_quantity or 0
        max_qty = item.max_quantity or 0
        batch_size = item.batch_size or 0
        delivery_days = item.restock_delivery_days or 7  # Default to 7 days if not set

        # Calculate order amount and priority
        order_amount = 0
        priority = "Not needed"

        # Time-based restock logic: consider delivery time and current stock percentage
        should_reorder = False
        reorder_reason = ""

        if min_qty > 0:
            stock_percentage = (current_total / min_qty) * 100

            # Always reorder if below minimum
            if current_total < min_qty:
                should_reorder = True
                reorder_reason = "Below minimum"
                priority = "High" if current_total == 0 else "Medium"

            # Time-based reordering: if stock is low and we need time for delivery
            elif stock_percentage <= 50 and delivery_days >= 3:
                should_reorder = True
                reorder_reason = "Time-based (low stock + delivery time)"
                priority = "Medium"

            # Very low stock percentage should trigger reorder regardless
            elif stock_percentage <= 25:
                should_reorder = True
                reorder_reason = "Very low stock (≤25%)"
                priority = "Medium"

        # If we should reorder, calculate the amount
        if should_reorder:
            if max_qty > 0:
                # Order up to max quantity
                needed = max_qty - current_total
                if batch_size > 0:
                    # Round up to nearest batch size
                    order_amount = ((needed + batch_size - 1) // batch_size) * batch_size
                else:
                    order_amount = needed
            elif batch_size > 0:
                # Use batch size as default order amount
                order_amount = batch_size
            else:
                # Default to bringing up to min quantity (or at least 1 if min is 0)
                order_amount = max(min_qty - current_total, 1)

        restock_data.append(
            {
                "item": item,
                "current_total": current_total,
                "min_quantity": min_qty,
                "max_quantity": max_qty,
                "batch_size": batch_size,
                "order_amount": order_amount,
                "priority": priority,
                "reorder_reason": reorder_reason if should_reorder else "Stock sufficient",
            }
        )

    # Sort by priority (High first, then Medium, then Not needed) and then by item name
    priority_order = {"High": 0, "Medium": 1, "Not needed": 2}
    restock_data.sort(key=lambda x: (priority_order[x["priority"]], x["item"].name))

    return render_template("admin_restock.html", squad=squad, restock_data=restock_data, admin=True)


@bp.route("/<squad>/admin-panel/view-locations")
def admin_view_locations(squad):
    locations = UserItemLocations.query.filter_by(user_id=current_user.id).order_by(UserItemLocations.name).all()
    return render_template("admin_view_locations.html", squad=squad, locations=locations, admin=True)


@bp.route("/<squad>/admin-panel/view-tags")
def admin_view_tags(squad):
    tags = UserItemTags.query.filter_by(user_id=current_user.id).order_by(UserItemTags.tag_name).all()
    return render_template("admin_view_tags.html", squad=squad, tags=tags, admin=True)


@bp.route("/<squad>/admin-panel/history")
def admin_history(squad):
    action_logs = ActionLogs.query.filter_by(user_id=current_user.id).order_by(ActionLogs.id.desc()).all()
    return render_template("admin_history.html", squad=squad, action_logs=action_logs, admin=True)


@bp.route("/<squad>/admin-panel/scan-items")
def admin_scan_items(squad):
    """Admin item selection screen for scanning"""
    items = Items.query.filter_by(user_id=current_user.id).order_by(Items.last_accessed.desc().nullslast()).all()
    return render_template("index.html", items=items, squad=squad, logo_img=current_user.image, admin=True)


@bp.route("/<squad>/admin-panel/scan")
def admin_scan_start(squad):
    """Admin entry point for scanning - decides scan_selection vs scan"""
    item_id = request.args.get("item_id")
    return handle_scan_start(squad, item_id, is_admin=True)


@bp.route("/<squad>/admin-panel/scan/locations", methods=["GET", "POST"])
def scan_locations(squad):
    """Admin select to and from locations for scanning"""
    if request.method == "POST":
        return handle_scan_locations_post(squad, request.form, is_admin=True)
    else:
        item_id = request.args.get("item_id")
        user_recount_allow = request.args.get("user_recount_allow", "True") == "True"
        user_take_allow = request.args.get("user_take_allow", "True") == "True"
        return handle_scan_locations_get(squad, item_id, user_recount_allow, user_take_allow, is_admin=True)


@bp.route("/<squad>/admin-panel/scan/item", methods=["GET", "POST"])
def scan_item(squad):
    """Admin scan item with locations already selected"""
    if request.method == "POST":
        return handle_scan_item_post(squad, request.form, is_admin=True)
    else:
        item_id = request.args.get("item_id")
        from_location_id = request.args.get("from_location_id")
        to_location_id = request.args.get("to_location_id")
        user_recount_allow = request.args.get("user_recount_allow", "True") == "True"
        user_take_allow = request.args.get("user_take_allow", "True") == "True"
        return handle_scan_item_get(
            squad, item_id, from_location_id, to_location_id, user_recount_allow, user_take_allow, is_admin=True
        )


# TODO RED: Add reports and analytics dashboard
# - Usage statistics (most/least accessed items)
# - Inventory trends over time (charts/graphs)
# - Low stock alerts and notifications
# - Restock recommendations based on usage patterns
