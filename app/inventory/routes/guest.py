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
from app.inventory.admin_edit_service import send_temporary_admin_pin
from app.inventory.constants import (
    UNKNOWN_UPC_INVALID_MESSAGE,
)
from app.inventory.scan_flow import (
    handle_scan_item_get,
    handle_scan_item_post,
    handle_scan_start,
    handle_scan_storages_get,
    handle_scan_storages_post,
)
from app.inventory.schema import ScanItemQuery, ScanStartQuery
from app.inventory.search_payload import load_item_search_payload
from app.inventory.upc_service import record_unknown_upc
from app.shared.database import get_session
from app.shared.rate_limit import AUTH_ATTEMPT_LIMITS, limiter
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
        logger.info("Guest route rejected: unauthenticated", extra={"squad": squad})
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
        unknown_upc_message = _record_unknown_upc_from_request(squad)
        logger.info("Guest scan barcode was not found", extra={"unknown_upc_recorded": bool(unknown_upc_message)})
        flash(unknown_upc_message or "Item not found. Please try again.", "warning")
    try:
        with get_session() as s:
            items_payload = load_item_search_payload(
                s,
                current_user.id,
                order_by_last_accessed=True,
            )
    except Exception:
        logger.exception("Guest inventory load failed", extra={"squad": squad})
        flash("Inventory could not load. Try again.", "error")
        items_payload = []
    return render_template(
        "index.html",
        items_payload=items_payload,
        squad=squad,
        logo_img=current_user.image,
    )


def _record_unknown_upc_from_request(squad: str) -> str | None:
    upc = request.args.get("unknown_upc", "").strip()
    if not upc:
        return None
    try:
        with get_session() as s:
            status = record_unknown_upc(s, current_user.id, upc)
            s.commit()
        return status.message
    except ValueError as exc:
        logger.info(
            "Unknown guest UPC scan ignored because the code was invalid",
            extra={"error": str(exc)},
        )
        return UNKNOWN_UPC_INVALID_MESSAGE


@bp.route("/<squad>/admin", methods=["GET", "POST"])
@limiter.limit("; ".join(AUTH_ATTEMPT_LIMITS), methods=["POST"])
def admin_login(squad: str) -> Any:
    token = current_device_token()
    if request.method == "POST":
        with get_session() as s:
            agency = get_agency_by_display_name(squad, s)
        if not agency:
            logger.warning("Admin PIN login rejected: unknown squad", extra={"squad": squad})
            flash("Invalid squad name.", "error")
            return _admin_login_response(squad, token)
        if request.form.get("action") == "send_temp_pin":
            with get_session() as s:
                agency = get_agency_by_display_name(squad, s)
                if agency is None or not send_temporary_admin_pin(s, agency):
                    flash("Temporary PIN could not be sent. Try again.", "error")
                    return _admin_login_response(squad, token)
                s.commit()
            flash("Temporary PIN sent to the account email.", "success")
            return _admin_login_response(squad, token)
        pin = request.form.get("password", "")
        if agency.check_pin(pin):
            session["admin"] = True
            session["admin_last_active"] = datetime.now(UTC).timestamp()
            logger.info("Admin PIN login succeeded", extra={"agency_id": agency.id, "squad": squad})
            flash("Admin access granted.", "success")
            response = make_response(redirect(url_for("admin.admin_panel", squad=squad)))
            set_device_cookie(response, token)
            return response
        logger.info("Admin PIN login rejected: invalid PIN", extra={"agency_id": agency.id, "squad": squad})
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
    query = ScanStartQuery.model_validate(request.args.to_dict())
    if get_device_location_id(current_user.id) is None:
        return redirect(url_for("guest.scan_location", squad=squad, item_id=query.item_id))
    return handle_scan_start(
        squad,
        query.item_id,
        upc=query.upc,
        is_admin=False,
    )


@bp.route("/<squad>/scan/location", methods=["GET", "POST"])
@login_required
def scan_location(squad: str) -> Any:
    item_id = parse_optional_int(request.values.get("item_id"))
    if item_id is None:
        logger.info("Device location selection rejected: missing item", extra={"squad": squad})
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
            logger.info(
                "Device location selection rejected",
                extra={
                    "agency_location_id": location_id,
                    "error": str(exc),
                },
            )
            flash(str(exc), "error")
            return redirect(url_for("guest.scan_location", squad=squad, item_id=item_id))
        logger.info(
            "Device location saved for guest scan flow",
            extra={
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
    query = ScanStartQuery.model_validate(request.args.to_dict())
    return handle_scan_storages_get(squad, query.item_id)


@bp.route("/<squad>/scan/item", methods=["GET", "POST"])
@login_required
def scan_item(squad: str) -> Any:
    if request.method == "POST":
        return handle_scan_item_post(squad, request.form, is_admin=False)
    query = ScanItemQuery.from_query(request.args.to_dict(), is_admin=False)
    return handle_scan_item_get(
        squad,
        query.item_id,
        query.from_storage_id,
        query.to_storage_id,
        show_scan_route=query.show_scan_route,
    )
