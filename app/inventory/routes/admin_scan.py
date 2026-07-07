"""Admin scan setup and scan route endpoints."""

from dataclasses import dataclass
from typing import Any

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user
from loguru import logger
from pydantic import ValidationError

from app.inventory import admin_bp as bp
from app.inventory.constants import UNKNOWN_UPC_INVALID_MESSAGE, UnknownUpcStatus
from app.inventory.scan_flow import (
    handle_scan_item_get,
    handle_scan_item_post,
    handle_scan_start,
    handle_scan_storages_get,
    handle_scan_storages_post,
)
from app.inventory.scan_support import (
    ScanPermissions,
    format_scan_location_label,
    format_scan_route_label,
    is_scan_route_allowed,
    load_scan_storage_choices,
    resolve_scan_location,
)
from app.inventory.schema import AdminScanRouteRequest, ScanItemQuery, ScanStartQuery
from app.inventory.search_payload import load_item_search_payload
from app.inventory.upc_service import record_unknown_upc
from app.shared.database import get_session


@dataclass(frozen=True, slots=True)
class AdminScanRouteSelection:
    from_storage_id: int
    to_storage_id: int
    from_label: str
    to_label: str
    label: str


@bp.route("/<squad>/admin-panel/scan-items", methods=["GET", "POST"])
def admin_scan_items(squad: str) -> Any:
    if request.method == "POST":
        return _save_admin_scan_route(squad)

    scan_route = _selected_admin_scan_route()
    if scan_route is None:
        return _render_admin_scan_setup(squad)

    if request.args.get("scan_error") == "not_found":
        unknown_upc = request.args.get("unknown_upc", "").strip()
        unknown_upc_status = _record_admin_unknown_upc(unknown_upc)
        logger.info(
            "Admin scan barcode was not found",
            extra={
                "upc": unknown_upc,
                "unknown_upc_status": unknown_upc_status.value if unknown_upc_status else None,
                "from_storage_id": scan_route.from_storage_id,
                "to_storage_id": scan_route.to_storage_id,
            },
        )
        if unknown_upc_status == UnknownUpcStatus.PENDING:
            flash("Choose the item this barcode should open.", "warning")
            return redirect(url_for("admin.pending_upcs", squad=squad, focus_upc=unknown_upc))
        if unknown_upc_status:
            message = unknown_upc_status.message
        elif unknown_upc:
            message = UNKNOWN_UPC_INVALID_MESSAGE
        else:
            message = "Item not found. Please try again."
        flash(message, "warning")
    with get_session() as s:
        items_payload = load_item_search_payload(
            s,
            current_user.id,
            include_inactive=False,
            order_by_last_accessed=True,
        )
    return render_template(
        "index.html",
        items_payload=items_payload,
        squad=squad,
        logo_img=current_user.image,
        admin=True,
        page_subtitle="Ready for barcode scan or item search",
        selected_scan_route=scan_route.label,
        selected_from_location_label=scan_route.from_label,
        selected_to_location_label=scan_route.to_label,
        selected_from_storage_id=scan_route.from_storage_id,
        selected_to_storage_id=scan_route.to_storage_id,
        scan_item_url_base=url_for("admin.scan_item", squad=squad),
        scan_error_url=url_for(
            "admin.admin_scan_items",
            squad=squad,
            from_storage_id=scan_route.from_storage_id,
            to_storage_id=scan_route.to_storage_id,
            scan_error="not_found",
        ),
    )


def _record_admin_unknown_upc(upc: str) -> UnknownUpcStatus | None:
    if not upc:
        return None
    try:
        with get_session() as s:
            status = record_unknown_upc(s, current_user.id, upc)
            s.commit()
        return status
    except ValueError as exc:
        logger.info("Unknown admin UPC scan ignored because the code was invalid", extra={"error": str(exc)})
        return None


@bp.route("/<squad>/admin-panel/scan")
def admin_scan_start(squad: str) -> Any:
    query = ScanStartQuery.model_validate(request.args.to_dict())
    return handle_scan_start(
        squad,
        query.item_id,
        upc=query.upc,
        is_admin=True,
    )


@bp.route("/<squad>/admin-panel/scan/storages", methods=["GET", "POST"])
def scan_storages(squad: str) -> Any:
    if request.method == "POST":
        return handle_scan_storages_post(squad, request.form, is_admin=True)
    query = ScanStartQuery.model_validate(request.args.to_dict())
    return handle_scan_storages_get(squad, query.item_id, is_admin=True)


@bp.route("/<squad>/admin-panel/scan/item", methods=["GET", "POST"])
def scan_item(squad: str) -> Any:
    if request.method == "POST":
        return handle_scan_item_post(squad, request.form, is_admin=True)
    query = ScanItemQuery.from_query(request.args.to_dict(), is_admin=True)
    return handle_scan_item_get(
        squad,
        query.item_id,
        query.from_storage_id,
        query.to_storage_id,
        is_admin=True,
    )


def _render_admin_scan_setup(squad: str) -> Any:
    with get_session() as s:
        storage_choices = load_scan_storage_choices(current_user.id, True, s)
        from_locations = storage_choices.from_storages
        to_locations = storage_choices.to_storages

    if not from_locations:
        logger.error("Admin scan setup failed: no valid source storages are available", extra={"squad": squad})
        flash("No valid storages found. Please check your location setup.", "error")
        return redirect(url_for("admin.admin_panel", squad=squad))

    query = ScanItemQuery.from_query(request.args.to_dict(), is_admin=True)
    return render_template(
        "admin_scan_setup.html",
        squad=squad,
        from_locations=from_locations,
        to_locations=to_locations,
        selected_from_id=query.from_storage_id,
        selected_to_id=query.to_storage_id,
        setup_subtitle="Choose the FROM and TO locations for the next scans",
        admin=True,
    )


def _save_admin_scan_route(squad: str) -> Any:
    try:
        route_request = AdminScanRouteRequest.model_validate(request.form.to_dict())
    except ValidationError as exc:
        logger.info("Admin scan setup rejected: submitted route form data was invalid", extra={"error": str(exc)})
        flash("Invalid form data. Please try again.", "error")
        return redirect(url_for("admin.admin_panel", squad=squad))

    if route_request.same_location_error == "1":
        logger.info(
            "Admin scan setup rejected: source and destination combination is not allowed",
            extra={"from_storage_id": route_request.from_storage_id, "to_storage_id": route_request.to_storage_id},
        )
        flash("Invalid storage combination.", "error")
        return redirect(
            url_for(
                "admin.admin_scan_items",
                squad=squad,
                from_storage_id=route_request.from_storage_id,
                to_storage_id=route_request.to_storage_id,
            )
        )

    if not _is_valid_admin_scan_route(route_request.from_storage_id, route_request.to_storage_id):
        logger.info(
            "Admin scan setup rejected: selected route is not allowed",
            extra={"from_storage_id": route_request.from_storage_id, "to_storage_id": route_request.to_storage_id},
        )
        flash("Choose valid scan locations.", "error")
        return redirect(url_for("admin.admin_scan_items", squad=squad))

    logger.info(
        "Admin scan route selected",
        extra={"from_storage_id": route_request.from_storage_id, "to_storage_id": route_request.to_storage_id},
    )
    return redirect(
        url_for(
            "admin.admin_scan_items",
            squad=squad,
            from_storage_id=route_request.from_storage_id,
            to_storage_id=route_request.to_storage_id,
        )
    )


def _selected_admin_scan_route() -> AdminScanRouteSelection | None:
    query = ScanItemQuery.from_query(request.args.to_dict(), is_admin=True)
    from_storage_id = query.from_storage_id
    to_storage_id = query.to_storage_id
    if not _is_valid_admin_scan_route(from_storage_id, to_storage_id):
        return None

    from_storage = resolve_scan_location(from_storage_id, current_user.id)
    to_storage = resolve_scan_location(to_storage_id, current_user.id, takeout_allowed=True)

    return AdminScanRouteSelection(
        from_storage_id=from_storage_id or 0,
        to_storage_id=to_storage_id or 0,
        from_label=format_scan_location_label(from_storage, is_admin=True),
        to_label=format_scan_location_label(to_storage, is_admin=True, takeout_allowed=True),
        label=format_scan_route_label(from_storage, to_storage, is_admin=True),
    )


def _is_valid_admin_scan_route(
    from_storage_id: int | None,
    to_storage_id: int | None,
) -> bool:
    permissions = ScanPermissions(count=True, restock=True)
    with get_session() as s:
        return is_scan_route_allowed(
            current_user.id,
            from_storage_id,
            to_storage_id,
            permissions,
            is_admin=True,
            session=s,
        )
