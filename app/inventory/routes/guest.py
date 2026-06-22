"""Guest blueprint routes."""

from datetime import UTC, datetime
from typing import Any

from flask import flash, make_response, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required
from loguru import logger

from app.auth.device_locations import (
    current_device_token,
    get_device_location_id,
    get_or_create_device,
    save_device_location,
    set_device_cookie,
)
from app.auth.queries import get_agency_by_display_name, list_top_locations
from app.inventory import guest_bp as bp
from app.inventory.constants import UNKNOWN_UPC_REVIEW_MESSAGE
from app.inventory.scan_flow import (
    handle_scan_item_get,
    handle_scan_item_post,
    handle_scan_start,
    handle_scan_storages_get,
    handle_scan_storages_post,
)
from app.inventory.search_payload import load_item_search_payload
from app.inventory.upc_service import record_unknown_upc
from app.shared.database import get_session
from app.shared.utils import (
    get_squad_from_request,
    is_static_request,
    validate_squad_access,
)
from app.shared.validators import parse_optional_int


@bp.before_request
def check_guest_auth() -> Any:
    if is_static_request():
        return None

    # Always clear admin session on guest routes
    session.pop("admin", None)
    session.pop("admin_last_active", None)

    squad = get_squad_from_request()
    if squad is None:
        return redirect(url_for("auth.login"))

    if not current_user.is_authenticated:
        logger.warning("Guest route rejected: unauthenticated", extra={"squad": squad})
        flash("You must be logged in.", "warning")
        return redirect(url_for("auth.login"))

    redirect_url = validate_squad_access(squad)
    if redirect_url:
        return redirect(redirect_url)

    return None


@bp.route("/<squad>/")
@login_required
def index(squad: str) -> Any:
    if request.args.get("scan_error") == "not_found":
        has_unknown_upc = _record_unknown_upc_from_request(squad)
        logger.warning(
            "Guest scan search could not find the scanned barcode",
            extra={"agency_id": current_user.id, "squad": squad},
        )
        flash(UNKNOWN_UPC_REVIEW_MESSAGE if has_unknown_upc else "Item not found. Please try again.", "warning")
    try:
        with get_session() as s:
            items_payload = load_item_search_payload(
                s,
                current_user.id,
                order_by_last_accessed=True,
            )
    except Exception:
        logger.exception(
            "Guest inventory load failed",
            extra={"agency_id": current_user.id, "squad": squad},
        )
        flash("Error loading inventory.", "error")
        items_payload = []
    return render_template(
        "index.html",
        items_payload=items_payload,
        squad=squad,
        logo_img=current_user.image,
    )


def _record_unknown_upc_from_request(squad: str) -> bool:
    upc = request.args.get("unknown_upc", "").strip()
    if not upc:
        return False
    try:
        with get_session() as s:
            record_unknown_upc(s, current_user.id, upc)
            s.commit()
        return True
    except ValueError as exc:
        logger.warning(
            "Unknown guest UPC scan ignored because the code was invalid",
            extra={"agency_id": current_user.id, "squad": squad, "error": str(exc)},
        )
        return False


@bp.route("/<squad>/admin", methods=["GET", "POST"])
def admin_login(squad: str) -> Any:
    token = current_device_token()
    if request.method == "POST":
        pin = request.form.get("password", "")
        with get_session() as s:
            agency = get_agency_by_display_name(squad, s)
        if not agency:
            logger.warning("Admin PIN login rejected: squad name was not found", extra={"squad": squad})
            flash("Invalid squad name.", "error")
            return _admin_login_response(squad, token)
        if agency.pin and pin == agency.pin:
            session["admin"] = True
            session["admin_last_active"] = datetime.now(UTC).timestamp()
            logger.info(
                "Admin PIN login succeeded for guest device session",
                extra={"agency_id": current_user.id, "squad": squad},
            )
            flash("Admin access granted.", "success")
            response = make_response(redirect(url_for("admin.admin_panel", squad=squad)))
            set_device_cookie(response, token)
            return response
        logger.warning(
            "Admin PIN login rejected: invalid PIN",
            extra={"agency_id": current_user.id, "squad": squad},
        )
        flash("Invalid PIN.", "error")
    return _admin_login_response(squad, token)


def _admin_login_response(squad: str, token: str) -> Any:
    with get_session() as s:
        locations = list_top_locations(current_user.id, s)
        device = get_or_create_device(current_user.id, token, s)
        selected_location_id = device.agency_location_id
        s.commit()
    response = make_response(
        render_template(
            "admin_login.html",
            squad=squad,
            locations=locations,
            selected_location_id=selected_location_id,
        )
    )
    set_device_cookie(response, token)
    return response


@bp.route("/<squad>/scan")
@login_required
def scan_start(squad: str) -> Any:
    if get_device_location_id(current_user.id) is None:
        return redirect(url_for("guest.scan_location", squad=squad, item_id=request.args.get("item_id")))
    return handle_scan_start(
        squad,
        parse_optional_int(request.args.get("item_id")),
        upc=request.args.get("upc"),
        is_admin=False,
    )


@bp.route("/<squad>/scan/location", methods=["GET", "POST"])
@login_required
def scan_location(squad: str) -> Any:
    item_id = parse_optional_int(request.values.get("item_id"))
    if item_id is None:
        logger.error(
            "Device location selection rejected: missing item",
            extra={"agency_id": current_user.id, "squad": squad},
        )
        flash("Item not found.", "error")
        return redirect(url_for("guest.index", squad=squad))

    if request.method == "POST":
        token = current_device_token()
        location_id = parse_optional_int(request.form.get("agency_location_id"))
        try:
            with get_session() as s:
                save_device_location(current_user.id, token, location_id, s)
                s.commit()
        except ValueError as exc:
            logger.warning(
                "Device location selection rejected",
                extra={
                    "agency_id": current_user.id,
                    "squad": squad,
                    "agency_location_id": location_id,
                    "error": str(exc),
                },
            )
            flash(str(exc), "error")
            return redirect(url_for("guest.scan_location", squad=squad, item_id=item_id))
        logger.debug(
            "Device location saved for guest scan flow",
            extra={
                "agency_id": current_user.id,
                "squad": squad,
                "item_id": item_id,
                "agency_location_id": location_id,
            },
        )
        response = make_response(redirect(url_for("guest.scan_storages", squad=squad, item_id=item_id)))
        set_device_cookie(response, token)
        return response

    with get_session() as s:
        locations = list_top_locations(current_user.id, s)
    return render_template("scan_location.html", squad=squad, item_id=item_id, locations=locations)


@bp.route("/<squad>/scan/storages", methods=["GET", "POST"])
@login_required
def scan_storages(squad: str) -> Any:
    if get_device_location_id(current_user.id) is None:
        return redirect(url_for("guest.scan_location", squad=squad, item_id=request.values.get("item_id")))
    if request.method == "POST":
        return handle_scan_storages_post(squad, request.form, is_admin=False)
    item_id = parse_optional_int(request.args.get("item_id"))
    user_count_allow = request.args.get("user_count_allow", "false").lower() == "true"
    user_restock_allow = request.args.get("user_restock_allow", "false").lower() == "true"
    return handle_scan_storages_get(squad, item_id, user_count_allow, user_restock_allow)


@bp.route("/<squad>/scan/item", methods=["GET", "POST"])
@login_required
def scan_item(squad: str) -> Any:
    if request.method == "POST":
        return handle_scan_item_post(squad, request.form, is_admin=False)
    item_id = parse_optional_int(request.args.get("item_id"))
    from_location_id = request.args.get("from_location_id")
    to_location_id = request.args.get("to_location_id")
    user_count_allow = request.args.get("user_count_allow", "false").lower() == "true"
    user_restock_allow = request.args.get("user_restock_allow", "false").lower() == "true"
    show_scan_route = request.args.get("show_scan_route") == "1"
    if to_location_id is None and not user_count_allow and not user_restock_allow:
        to_location_id = "-1"
    return handle_scan_item_get(
        squad,
        item_id,
        from_location_id,
        to_location_id,
        user_count_allow,
        user_restock_allow,
        show_scan_route=show_scan_route,
    )
