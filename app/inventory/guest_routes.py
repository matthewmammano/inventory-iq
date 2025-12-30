from datetime import UTC, datetime

from flask import flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required
from loguru import logger

from app.auth.user_queries import get_user_by_display_name, get_user_permissions
from app.core.route_validation import RouteValidationService
from app.db import get_session
from app.inventory import guest_bp as bp
from app.inventory.item_queries import list_items_for_user
from app.inventory.scan_operations import (
    handle_scan_item_get,
    handle_scan_item_post,
    handle_scan_locations_get,
    handle_scan_locations_post,
    handle_scan_start,
)


def _parse_int_optional(val: str | None) -> int | None:
    """Parse an optional string to int, return None if not present or invalid."""
    if val is None:
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


@bp.before_request
def check_authentication_and_squad():
    """Reset admin session and validate guest access."""
    if RouteValidationService.is_static_request():
        return

    # Reset admin session for all guest routes
    session.pop("admin", None)
    session.pop("admin_last_active", None)

    squad = RouteValidationService.get_squad_from_request()

    # Ensure `squad` is a string before passing to validators (Pylance-friendly)
    if squad is None:
        return redirect(url_for("auth.login"))

    # Chain validations - return first error found
    for validation in [
        RouteValidationService.validate_user_authentication(),
        RouteValidationService.validate_squad_access(squad),
    ]:
        if validation:
            return redirect(validation)


@bp.route("/<squad>/")
@login_required
def index(squad):
    """
    Display the inventory for the given squad to search or scan UPC.
    """
    # Check for UPC error parameter
    upc_error = request.args.get("upc_error")
    if upc_error:
        logger.warning(
            f"UPC scan error for user {current_user.email}: UPC {upc_error} not found"
        )
        flash(
            f"UPC {upc_error} not found in inventory. Please make sure you are scanning the appropriate item card on shelf.",
            "error",
        )

    # Get the list of items and order them by last_accessed
    try:
        with get_session() as db_session:
            items = list(
                list_items_for_user(
                    current_user.id,
                    include_inactive=False,
                    order_by_last_accessed=True,
                    session=db_session,
                )
            )
    except Exception as e:
        logger.error(f"Database error fetching items for user {current_user.id}: {e}")
        flash("Error loading inventory. Please try again.", "error")
        items = []
    return render_template(
        "index.html", items=items, squad=squad, logo_img=current_user.image
    )


@bp.route("/<squad>/scan")
@login_required
def scan_start(squad):
    """Entry point for scanning - decides scan_selection vs scan"""
    item_id = _parse_int_optional(request.args.get("item_id"))
    return handle_scan_start(squad, item_id, is_admin=False)


@bp.route("/<squad>/scan/locations", methods=["GET", "POST"])
@login_required
def scan_locations(squad):
    """Select to and from locations for scanning"""
    if request.method == "POST":
        return handle_scan_locations_post(squad, request.form, is_admin=False)
    else:
        item_id = _parse_int_optional(request.args.get("item_id"))
        # Get user permissions or use request override (default to False for guest)
        perms = get_user_permissions(squad)
        user_count_allow = (
            request.args.get("user_count_allow") == "True"
            if "user_count_allow" in request.args
            else (perms[0] if perms else False)
        )
        user_restock_allow = (
            request.args.get("user_restock_allow") == "True"
            if "user_restock_allow" in request.args
            else (perms[1] if perms else False)
        )
        user_take_allow = (
            request.args.get("user_take_allow") == "True"
            if "user_take_allow" in request.args
            else (perms[2] if perms else True)
        )
        return handle_scan_locations_get(
            squad,
            item_id,
            user_count_allow,
            user_restock_allow,
            user_take_allow,
        )


@bp.route("/<squad>/scan/item", methods=["GET", "POST"])
@login_required
def scan_item(squad):
    """Scan item with locations alerady selected (automatically if only one each)"""
    if request.method == "POST":
        return handle_scan_item_post(squad, request.form, is_admin=False)
    else:
        item_id = _parse_int_optional(request.args.get("item_id"))
        from_location_id = request.args.get("from_location_id")
        to_location_id = request.args.get("to_location_id")
        user_count_allow = request.args.get("user_count_allow", "False") == "True"
        user_restock_allow = request.args.get("user_restock_allow", "False") == "True"
        user_take_allow = request.args.get("user_take_allow", "True") == "True"

        # Infer TAKEOUT operation when to_location_id missing and it's the only allowed operation
        if (
            to_location_id is None
            and not user_count_allow
            and not user_restock_allow
            and user_take_allow
        ):
            to_location_id = "-1"
        return handle_scan_item_get(
            squad,
            item_id,
            from_location_id,
            to_location_id,
            user_count_allow,
            user_restock_allow,
            user_take_allow,
            is_admin=False,
        )


# Admin login page using PIN from Users DB
@bp.route("/<squad>/admin", methods=["GET", "POST"])
def admin_login(squad):
    if request.method == "POST":
        password = request.form["password"]
        try:
            with get_session() as db_session:
                user = get_user_by_display_name(squad, db_session)

            if not user:
                logger.warning(f"Admin login attempt for non-existent squad: {squad}")
                flash("Invalid squad name. Please try again.", "error")
                return render_template("admin_login.html", squad=squad, admin=True)

            correct_password = user.pin
        except Exception as e:
            logger.error(f"Database error during admin login for squad '{squad}': {e}")
            flash("Database error. Please try again.", "error")
            return render_template("admin_login.html", squad=squad, admin=True)

        if user.pin and password == correct_password:
            session["admin"] = True
            session["admin_last_active"] = datetime.now(UTC).timestamp()
            flash("Admin access granted.", "success")
            return redirect(url_for("admin.admin_panel", squad=squad))
        else:
            logger.warning(
                f"Failed admin login attempt for squad '{squad}' - invalid PIN"
            )
            flash("Invalid PIN entered. Please try again.", "error")
            return render_template("admin_login.html", squad=squad, admin=True)

    return render_template("admin_login.html", squad=squad, admin=True)
