import json

from dotenv import load_dotenv
from flask import current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user
from loguru import logger
from sqlalchemy.orm import joinedload

from app.auth.location_queries import list_locations
from app.auth.tag_queries import get_tags_by_ids, list_tags
from app.core.route_validation import RouteValidationService
from app.db import get_session
from app.inventory import admin_bp as bp
from app.inventory.item_queries import get_item, list_items_for_user
from app.inventory.models import ActionLogs, Items
from app.inventory.quantity_service import calculate_item_quantities
from app.inventory.scan_operations import (
    handle_scan_item_get,
    handle_scan_item_post,
    handle_scan_locations_get,
    handle_scan_locations_post,
    handle_scan_start,
)
from app.inventory.threshold_utilities import (
    get_days_until_low_threshold_class,
    get_inventory_level_threshold_class,
    get_order_quantity_threshold_class,
)
from app.prediction.bulk_service import BulkService
from app.utils.timezone_utils import get_timezone_display_hint

load_dotenv()

ADMIN_TIMEOUT_SECONDS = 21600  # 6 hours


def _parse_optional_int(value: str | None) -> int | None:
    """Safely parse an optional integer from a query string value.

    Returns None if the input is None or cannot be parsed as int.
    """
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


@bp.before_request
def check_admin_authorization():
    """Secure all admin routes with centralized validation."""
    if RouteValidationService.is_static_request():
        return

    # Ensure squad is always a string for downstream validators. If missing,
    # default to the current user's display name so validation functions get a str.
    squad = RouteValidationService.get_squad_from_request() or ""

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
        logger.warning(
            f"Unauthorized squad access: user {current_user.email} tried to access squad {squad}"
        )
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
    with get_session() as session:
        items = list(
            list_items_for_user(current_user.id, include_inactive=True, session=session)
        )
        tags = list_tags(current_user.id, session)
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
    return render_template(
        "admin_help.html", squad=squad, contact_phone=developer_phone, admin=True
    )


# Admin edit items in table page (protected)
@bp.route("/<squad>/admin-panel/edit-items", methods=["GET", "POST"])
def save_items(squad):
    if request.method == "GET":
        with get_session() as session:
            items = list(
                list_items_for_user(
                    current_user.id, include_inactive=True, session=session
                )
            )
            tags = list_tags(current_user.id, session)
        return render_template(
            "admin_edit_items.html",
            squad=squad,
            items=items,
            tags=tags,
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

    with get_session() as session:
        existing_ids = set(
            item.id
            for item in list_items_for_user(current_user.id, True, session=session)
        )
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
            tag_ids = [
                int(x.strip()) for x in tag_ids.split(",") if x.strip().isdigit()
            ]
        increments = item_data.get("increments")
        image = item_data.get("image", "").strip()

        # Validate tag_ids if provided
        if tag_ids:
            try:
                with get_session() as session:
                    valid_tags = list(
                        get_tags_by_ids(current_user.id, tag_ids, session=session)
                    )
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
                # Update existing item within its own session so changes persist

                with get_session() as session:
                    item = get_item(item_id, session)
                    if not item or item.user_id != current_user.id:
                        error_items.append(name)
                        continue

                    item.name = name
                    item.active = active
                    item.tag_ids = tag_ids
                    item.increments = increments if increments else None
                    item.image = image if image else None
                    session.add(item)
                    session.commit()
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
                with get_session() as session:
                    session.add(item)
                    session.flush()
                new_items.append(item)
            except Exception as e:
                logger.error(
                    f"Error creating item {name} for admin {current_user.email}: {e}"
                )
                error_items.append(name)
                continue

    # Delete items that were removed from the form
    with get_session() as session:
        for item_id in existing_ids - processed_ids:
            item_to_delete = get_item(item_id, session)
            if item_to_delete and item_to_delete.user_id == current_user.id:
                session.delete(item_to_delete)

    # All changes committed within individual session contexts above
    logger.info(
        f"Admin {current_user.email} saved items: {len(new_items)} new, {len(existing_ids - processed_ids)} deleted"
    )

    if error_items:
        logger.warning(
            f"Admin {current_user.email} had errors with items: {error_items}"
        )
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
    with get_session() as session:
        items = list(
            list_items_for_user(
                current_user.id,
                include_inactive=False,
                session=session,
            )
        )
        locations = list_locations(current_user.id, session=session)

        qty_lookup: dict[tuple[int, int], int] = {}
        for item in items:
            qty_by_location = calculate_item_quantities(
                session, current_user.id, item.id
            )
            for loc_id, qty in qty_by_location.items():
                qty_lookup[(item.id, loc_id)] = qty

    # Build the data structure for the template
    inventory_data = []
    for item in items:
        row_data = {
            "item": item,
            "location_counts": {},
            "location_classes": {},
            "total": 0,
        }

        for location in locations:
            count = qty_lookup.get((item.id, location.id), 0)
            row_data["location_counts"][location.id] = count
            row_data["location_classes"][location.id] = (
                get_inventory_level_threshold_class(count)
            )
            row_data["total"] += count

        # Add threshold class for total
        row_data["total_class"] = get_inventory_level_threshold_class(row_data["total"])
        inventory_data.append(row_data)

    return render_template(
        "admin_inventory_counts.html",
        squad=squad,
        inventory_data=inventory_data,
        locations=locations,
        admin=True,
    )


@bp.route("/<squad>/admin-panel/restock")
def restock(squad):
    """Display items that need restocking with calculated order amounts"""
    try:
        # Single function call handles everything: recalculation + predictions + formatting
        with get_session() as session:
            restock_data = BulkService.get_restock_analysis(session, current_user.id)

            # Add threshold classes for visual indicators
            for item_data in restock_data:
                item_data["order_class"] = get_order_quantity_threshold_class(
                    item_data.get("order_amount") or 0
                )
                item_data["current_total_class"] = get_inventory_level_threshold_class(
                    item_data.get("current_total") or 0
                )
                item_data["estimated_total_class"] = (
                    get_inventory_level_threshold_class(
                        item_data.get("estimated_total") or 0
                    )
                )
                item_data["days_class"] = get_days_until_low_threshold_class(
                    item_data.get("days_until_low") or 0
                )

        # TODO-5: Add client-side table sorting and filtering functionality for all admin table views
        # Should include: sortable columns, search/filter by item name, filter by threshold ranges,
        # filter by days until low, order amount ranges, and inventory levels (negative/zero/normal)
        return render_template(
            "admin_restock.html", squad=squad, restock_data=restock_data, admin=True
        )
    except Exception as e:
        logger.error(f"Restock analysis failed for user {current_user.id}: {e}")
        flash("Error loading restock analysis. Please try again.", "error")
        return render_template(
            "admin_restock.html", squad=squad, restock_data=[], admin=True
        )


@bp.route("/<squad>/admin-panel/view-locations")
def admin_view_locations(squad):
    with get_session() as session:
        locations = list_locations(current_user.id, session=session)
    return render_template(
        "admin_view_locations.html", squad=squad, locations=locations, admin=True
    )


@bp.route("/<squad>/admin-panel/view-tags")
def admin_view_tags(squad):
    with get_session() as session:
        tags = list_tags(current_user.id, session)
    return render_template("admin_view_tags.html", squad=squad, tags=tags, admin=True)


@bp.route("/<squad>/admin-panel/history")
def admin_history(squad):
    with get_session() as session:
        action_logs = list(
            session.query(ActionLogs)
            .options(
                joinedload(ActionLogs.item),
                joinedload(ActionLogs.from_location),
                joinedload(ActionLogs.to_location),
            )
            .filter(ActionLogs.user_id == current_user.id)
            .order_by(ActionLogs.id.desc())
            .all()
        )
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
        logger.warning(
            f"UPC scan error for admin {current_user.email}: UPC {upc_error} not found"
        )
        flash(
            f"UPC {upc_error} not found in inventory. Please make sure you are scanning the appropriate item card on shelf.",
            "error",
        )

    with get_session() as session:
        items = list(
            list_items_for_user(
                current_user.id,
                include_inactive=True,
                order_by_last_accessed=True,
                session=session,
            )
        )
    return render_template(
        "index.html", items=items, squad=squad, logo_img=current_user.image, admin=True
    )


@bp.route("/<squad>/admin-panel/scan")
def admin_scan_start(squad):
    """Admin entry point for scanning - decides scan_selection vs scan"""
    item_id_raw = request.args.get("item_id")
    item_id = _parse_optional_int(item_id_raw)
    return handle_scan_start(squad, item_id, is_admin=True)


@bp.route("/<squad>/admin-panel/scan/locations", methods=["GET", "POST"])
def scan_locations(squad):
    """Admin select to and from locations for scanning"""
    if request.method == "POST":
        return handle_scan_locations_post(squad, request.form, is_admin=True)
    else:
        item_id = _parse_optional_int(request.args.get("item_id"))
        user_count_allow = request.args.get("user_count_allow", "True") == "True"
        user_restock_allow = request.args.get("user_restock_allow", "True") == "True"
        user_take_allow = request.args.get("user_take_allow", "True") == "True"
        return handle_scan_locations_get(
            squad,
            item_id,
            user_count_allow,
            user_restock_allow,
            user_take_allow,
            is_admin=True,
        )


@bp.route("/<squad>/admin-panel/scan/item", methods=["GET", "POST"])
def scan_item(squad):
    """Admin scan item with locations already selected"""
    if request.method == "POST":
        return handle_scan_item_post(squad, request.form, is_admin=True)
    else:
        item_id = _parse_optional_int(request.args.get("item_id"))
        from_location_id = _parse_optional_int(request.args.get("from_location_id"))
        to_location_id = _parse_optional_int(request.args.get("to_location_id"))
        user_count_allow = request.args.get("user_count_allow", "True") == "True"
        user_restock_allow = request.args.get("user_restock_allow", "True") == "True"
        user_take_allow = request.args.get("user_take_allow", "True") == "True"

        # Infer TAKEOUT operation when to_location_id missing and it's the only allowed operation
        if (
            to_location_id is None
            and not user_count_allow
            and not user_restock_allow
            and user_take_allow
        ):
            to_location_id = -1
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


# TODO-3: Add color coding to restock table cells
# - Red: Days until low <= 3 (urgent)
# - Orange: Days until low <= 7 (soon)
# - Yellow: Days until low <= 14 (watch)
# - Green: Days until low > 14 (good)
# - Gray: No prediction available (insufficient data)

# TODO-3: When in ADMIN mode could scan location be chosen BEFORE the search is made
# - This way don't have to select each time when doing repetitive things and changes
# - Add location pre-selection on admin scan items page for workflow efficiency
