import json
import logging

from dotenv import load_dotenv
from flask import current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user

from app import db
from app.auth.models import UserItemLocations, UserItemTags
from app.core.route_validation import RouteValidationService
from app.inventory import admin_bp as bp
from app.inventory.models import ActionLogs, ItemLocationQuantities, Items
from app.inventory.scan_operations import (
    handle_scan_item_get,
    handle_scan_item_post,
    handle_scan_locations_get,
    handle_scan_locations_post,
    handle_scan_start,
)
from app.prediction.bulk_service import BulkService
from app.utils.timezone_utils import get_timezone_display_hint
from app.inventory.threshold_utilities import (
    get_inventory_level_threshold_class,
    get_order_quantity_threshold_class,
    get_days_until_low_threshold_class,
    format_order_amount_display,
    format_days_until_low_display,
)

logger = logging.getLogger(__name__)

load_dotenv()

ADMIN_TIMEOUT_SECONDS = 21600  # 6 hours


@bp.before_request
def check_admin_authorization():
    """Secure all admin routes with centralized validation."""
    if RouteValidationService.is_static_request():
        return

    squad = RouteValidationService.get_squad_from_request()

    # Chain validations - return first error found
    for validation in [
        RouteValidationService.validate_user_authentication(),
        RouteValidationService.validate_squad_access(squad),
        RouteValidationService.validate_admin_session(squad, ADMIN_TIMEOUT_SECONDS),
    ]:
        if validation:
            return redirect(validation)

    # Verify user belongs to requested squad
    if current_user.display_name != squad:
        logger.warning(f"Unauthorized squad access: user {current_user.email} tried to access squad {squad}")
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
    timezone_hint = get_timezone_display_hint(current_user.timezone)
    return render_template(
        "admin_view_items.html",
        squad=squad,
        items=items,
        tags=tags,
        admin=True,
        user_timezone=current_user.timezone,
        timezone_hint=timezone_hint,
    )


# Admin help page (protected)
@bp.route("/<squad>/help")
def help_page(squad):
    developer_phone = current_app.config["CONTACT_PHONE"]
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
        logger.warning(f"No item data received from admin {current_user.email}")
        flash("No item data received", "warning")
        return redirect(url_for("admin.admin_view_items", squad=squad))

    try:
        items_list = json.loads(items_data)
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error for admin {current_user.email}: {e}")
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
            except Exception as e:
                logger.error(f"Error creating item {name} for admin {current_user.email}: {e}")
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
        logger.info(
            f"Admin {current_user.email} saved items: {len(new_items)} new, {len(existing_ids - processed_ids)} deleted"
        )
    except Exception as e:
        db.session.rollback()
        logger.error(f"Database error saving items for admin {current_user.email}: {e}")
        flash("Database error occurred. Please try again.", "error")

    if error_items:
        logger.warning(f"Admin {current_user.email} had errors with items: {error_items}")
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
        row_data = {"item": item, "location_counts": {}, "location_classes": {}, "total": 0}

        for location in locations:
            count = qty_lookup.get((item.id, location.id), 0)
            row_data["location_counts"][location.id] = count
            row_data["location_classes"][location.id] = get_inventory_level_threshold_class(count)
            row_data["total"] += count

        # Add threshold class for total
        row_data["total_class"] = get_inventory_level_threshold_class(row_data["total"])
        inventory_data.append(row_data)

    return render_template(
        "admin_inventory_counts.html", squad=squad, inventory_data=inventory_data, locations=locations, admin=True
    )


@bp.route("/<squad>/admin-panel/restock")
def restock(squad):
    """Display items that need restocking with calculated order amounts"""
    try:
        # Single function call handles everything: recalculation + predictions + formatting
        restock_data = BulkService.get_restock_analysis(db.session, current_user.id)

        # Add threshold classes for visual indicators
        for item_data in restock_data:
            item_data['order_class'] = get_order_quantity_threshold_class(item_data.get('order_amount'))
            item_data['current_total_class'] = get_inventory_level_threshold_class(item_data.get('current_total'))
            item_data['estimated_total_class'] = get_inventory_level_threshold_class(item_data.get('estimated_total'))
            item_data['days_class'] = get_days_until_low_threshold_class(item_data.get('days_until_low'))

        # TODO RED: Add client-side table sorting and filtering functionality for all admin table views
        # Should include: sortable columns, search/filter by item name, filter by threshold ranges,
        # filter by days until low, order amount ranges, and inventory levels (negative/zero/normal)
        return render_template("admin_restock.html", squad=squad, restock_data=restock_data, admin=True)
    except Exception as e:
        logger.error(f"Restock analysis failed for user {current_user.id}: {e}")
        flash("Error loading restock analysis. Please try again.", "error")
        return render_template("admin_restock.html", squad=squad, restock_data=[], admin=True)


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
    timezone_hint = get_timezone_display_hint(current_user.timezone)
    return render_template(
        "admin_history.html",
        squad=squad,
        action_logs=action_logs,
        admin=True,
        user_timezone=current_user.timezone,
        timezone_hint=timezone_hint,
    )


@bp.route("/<squad>/admin-panel/scan-items")
def admin_scan_items(squad):
    """Admin item selection screen for scanning"""
    # Check for UPC error parameter
    upc_error = request.args.get("upc_error")
    if upc_error:
        logger.warning(f"UPC scan error for admin {current_user.email}: UPC {upc_error} not found")
        flash(
            f"UPC {upc_error} not found in inventory. Please make sure you are scanning the appropriate item card on shelf.",
            "error",
        )

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
        user_count_allow = request.args.get("user_count_allow", "True") == "True"
        user_restock_allow = request.args.get("user_restock_allow", "True") == "True"
        user_take_allow = request.args.get("user_take_allow", "True") == "True"
        return handle_scan_locations_get(
            squad, item_id, user_count_allow, user_restock_allow, user_take_allow, is_admin=True
        )


@bp.route("/<squad>/admin-panel/scan/item", methods=["GET", "POST"])
def scan_item(squad):
    """Admin scan item with locations already selected"""
    if request.method == "POST":
        return handle_scan_item_post(squad, request.form, is_admin=True)
    else:
        item_id = request.args.get("item_id")
        from_location_id = request.args.get("from_location_id")
        to_location_id = request.args.get("to_location_id")
        user_count_allow = request.args.get("user_count_allow", "True") == "True"
        user_restock_allow = request.args.get("user_restock_allow", "True") == "True"
        user_take_allow = request.args.get("user_take_allow", "True") == "True"
        return handle_scan_item_get(
            squad,
            item_id,
            from_location_id,
            to_location_id,
            user_count_allow,
            user_restock_allow,
            user_take_allow,
            is_admin=True,
        )


# TODO YELLOW: Add color coding to restock table cells
# - Red: Days until low <= 3 (urgent)
# - Orange: Days until low <= 7 (soon)
# - Yellow: Days until low <= 14 (watch)
# - Green: Days until low > 14 (good)
# - Gray: No prediction available (insufficient data)

# TODO YELLOW: When in ADMIN mode could scan location be chosen BEFORE the search is made
# - This way don't have to select each time when doing repetitive things and changes
# - Add location pre-selection on admin scan items page for workflow efficiency
