from dotenv import load_dotenv
from flask import current_app, flash, redirect, render_template, request, url_for
from flask.typing import ResponseReturnValue
from flask_login import current_user
from loguru import logger
from sqlalchemy.orm import joinedload

from app.auth.location_queries import list_locations
from app.auth.tag_queries import list_tags
from app.auth.user_queries import get_user_permissions
from app.core.route_validation import RouteValidationService
from app.db import get_session
from app.inventory import admin_bp as bp
from app.inventory.data.item_queries import list_items_for_user
from app.inventory.data.models import ActionLogs
from app.inventory.data.quantity import calculate_item_quantities
from app.inventory.services.scanner import (
    handle_scan_item_get,
    handle_scan_item_post,
    handle_scan_locations_get,
    handle_scan_locations_post,
    handle_scan_start,
)
from app.inventory.ui.threshold_display import (
    get_days_until_low_threshold_class,
    get_inventory_level_threshold_class,
    get_order_quantity_threshold_class,
)
from app.prediction.bulk_service import BulkService
from app.utils.parsing import parse_optional_int
from app.utils.timezone_utils import get_timezone_display_hint

load_dotenv()

ADMIN_TIMEOUT_SECONDS = 2 * 60 * 60  # 2 hours


@bp.before_request
def check_admin_authorization() -> ResponseReturnValue:
    """Validate admin authorization and secure admin routes."""
    if RouteValidationService.is_static_request():
        return None

    squad = RouteValidationService.get_squad_from_request() or ""

    for validation in [
        RouteValidationService.validate_user_authentication(),
        RouteValidationService.validate_squad_access(squad),
        RouteValidationService.validate_admin_session(squad, ADMIN_TIMEOUT_SECONDS),
    ]:
        if validation:
            return redirect(validation)

    if current_user.display_name != squad:
        logger.warning(
            f"Unauthorized squad access: user {current_user.email} tried to access squad {squad}"
        )
        flash("You do not have permission to access this squad.", "warning")
        return redirect(url_for("auth.login"))
    return None


@bp.route("/<squad>/admin-panel")
def admin_panel(squad: str) -> ResponseReturnValue:
    """Render main admin dashboard."""
    return render_template("admin_panel.html", squad=squad, admin=True)


@bp.route("/<squad>/admin-panel/views")
def admin_panel_views(squad: str) -> ResponseReturnValue:
    """Render admin view selector."""
    return render_template("admin_panel_views.html", squad=squad, admin=True)


@bp.route("/<squad>/admin-panel/view-items")
def admin_view_items(squad: str) -> ResponseReturnValue:
    """Render inventory items list."""
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


@bp.route("/<squad>/help")
def help_page(squad: str) -> ResponseReturnValue:
    """Render help page with contact info."""
    developer_phone = current_app.config["CONTACT_PHONE"]
    return render_template(
        "admin_help.html", squad=squad, contact_phone=developer_phone, admin=True
    )


@bp.route("/<squad>/admin-panel/edit-items", methods=["GET", "POST"])
def save_items(squad: str) -> ResponseReturnValue:
    """Handle GET/POST for batch item editing."""
    if request.method == "GET":
        with get_session() as session:
            items = list_items_for_user(
                current_user.id, include_inactive=True, session=session
            )
            tags = list_tags(current_user.id, session)
        return render_template(
            "admin_edit_items.html",
            squad=squad,
            items=items,
            tags=tags,
            admin=True,
        )

    from app.inventory.data.item_queries import batch_update_items

    result = batch_update_items(current_user.id, request.form.get("itemsData"))
    if result.errors:
        flash(f"Errors: {', '.join(result.errors)}", "warning")
    else:
        flash("All items saved successfully!", "success")
    return redirect(url_for("admin.admin_view_items", squad=squad))


@bp.route("/<squad>/admin-panel/inventory-count-levels")
def inventory_counts(squad: str) -> ResponseReturnValue:
    """Display inventory counts across all locations."""
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
def restock(squad: str) -> ResponseReturnValue:
    """Render restock analysis with ML predictions."""
    try:
        with get_session() as session:
            restock_data = BulkService.get_restock_analysis(session, current_user.id)

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
def admin_view_locations(squad: str) -> ResponseReturnValue:
    """Render location list and management."""
    with get_session() as session:
        locations = list_locations(current_user.id, session=session)
    return render_template(
        "admin_view_locations.html", squad=squad, locations=locations, admin=True
    )


@bp.route("/<squad>/admin-panel/view-tags")
def admin_view_tags(squad: str) -> ResponseReturnValue:
    """Render tag list and management."""
    with get_session() as session:
        tags = list_tags(current_user.id, session)
    return render_template("admin_view_tags.html", squad=squad, tags=tags, admin=True)


@bp.route("/<squad>/admin-panel/history")
def admin_history(squad: str) -> ResponseReturnValue:
    """Render action history log for auditing."""
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
def admin_scan_items(squad: str) -> ResponseReturnValue:
    """Render item scanning interface."""
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
def admin_scan_start(squad: str) -> ResponseReturnValue:
    """Handle scan workflow initialization."""
    item_id = parse_optional_int(request.args.get("item_id"))
    return handle_scan_start(squad, item_id, is_admin=True)


@bp.route("/<squad>/admin-panel/scan/locations", methods=["GET", "POST"])
def scan_locations(squad: str) -> ResponseReturnValue:
    """Handle GET/POST for location scanning."""
    if request.method == "POST":
        return handle_scan_locations_post(squad, request.form, is_admin=True)
    else:
        item_id = parse_optional_int(request.args.get("item_id"))
        perms = get_user_permissions(squad)
        user_count_allow = (
            request.args.get("user_count_allow") == "False"
            and False
            or (perms[0] if perms else True)
        )
        user_restock_allow = (
            request.args.get("user_restock_allow") == "False"
            and False
            or (perms[1] if perms else True)
        )
        user_take_allow = (
            request.args.get("user_take_allow") == "False"
            and False
            or (perms[2] if perms else True)
        )
        return handle_scan_locations_get(
            squad,
            item_id,
            user_count_allow,
            user_restock_allow,
            user_take_allow,
            is_admin=True,
        )


@bp.route("/<squad>/admin-panel/scan/item", methods=["GET", "POST"])
def scan_item(squad: str) -> ResponseReturnValue:
    """Handle GET/POST for item scanning."""
    if request.method == "POST":
        return handle_scan_item_post(squad, request.form, is_admin=True)
    else:
        item_id = parse_optional_int(request.args.get("item_id"))
        from_location_id = parse_optional_int(request.args.get("from_location_id"))
        to_location_id = parse_optional_int(request.args.get("to_location_id"))
        perms = get_user_permissions(squad)
        user_count_allow = (
            request.args.get("user_count_allow") == "False"
            and False
            or (perms[0] if perms else True)
        )
        user_restock_allow = (
            request.args.get("user_restock_allow") == "False"
            and False
            or (perms[1] if perms else True)
        )
        user_take_allow = (
            request.args.get("user_take_allow") == "False"
            and False
            or (perms[2] if perms else True)
        )

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
