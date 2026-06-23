"""Admin blueprint routes for inventory management."""

from collections.abc import Mapping
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from typing import Any
from zoneinfo import ZoneInfo

from flask import current_app, flash, make_response, redirect, render_template, request, url_for
from flask_login import current_user
from loguru import logger
from pydantic import ValidationError
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.auth.device_locations import (
    current_device_token,
    get_device_location_id,
    save_device_location,
    set_device_cookie,
)
from app.auth.models import Agencies, AgencyEmails, AgencyLocations
from app.auth.queries import list_tags, list_top_locations
from app.inventory import admin_bp as bp
from app.inventory.bulk_location_service import (
    LocationQuantityGrid,
    load_location_item_selection,
    load_location_item_summary,
    load_location_quantity_grid,
    required_count_storage_ids,
    save_bulk_location_count,
    save_bulk_location_restock,
)
from app.inventory.constants import UNKNOWN_UPC_REVIEW_MESSAGE, UnknownUpcStatus
from app.inventory.item_queries import list_items
from app.inventory.location_operations import (
    build_location_count_rows,
    get_location_storages,
    parse_quantity_grid,
)
from app.inventory.models import ActionLogs, Items
from app.inventory.report_email_service import send_inventory_count_report
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
from app.inventory.schema import AdminScanRouteRequest
from app.inventory.search_payload import load_item_search_payload
from app.inventory.ui import (
    get_days_until_low_class,
    get_inventory_level_class,
    get_order_quantity_class,
)
from app.inventory.upc_service import (
    ignore_unknown_upc,
    list_review_unknown_upcs,
    record_unknown_upc,
    remove_unknown_upc,
    resolve_unknown_upc,
    unignore_unknown_upc,
)
from app.prediction.bulk_service import BulkService
from app.prediction.history_service import build_item_trend_chart
from app.shared.cache import ttl_cache
from app.shared.constants import ADMIN_TIMEOUT
from app.shared.database import get_session
from app.shared.timezone_utils import get_timezone_hint
from app.shared.utils import (
    get_squad_from_request,
    is_static_request,
    validate_admin_session,
    validate_squad_access,
)
from app.shared.validators import parse_optional_int

HISTORY_PAGE_SIZE = 250
HISTORY_PRINT_LIMIT = 5000


@bp.before_request
def check_admin() -> Any:
    if is_static_request():
        return None

    squad = get_squad_from_request() or ""
    if not current_user.is_authenticated:
        logger.warning("Admin route rejected: unauthenticated")
        flash("You must be logged in.", "warning")
        return redirect(url_for("auth.login"))

    for redirect_url in [
        validate_squad_access(squad),
        validate_admin_session(squad, ADMIN_TIMEOUT),
    ]:
        if redirect_url:
            return redirect(redirect_url)

    if current_user.display_name != squad:
        logger.warning(
            "Admin route rejected: squad mismatch",
            extra={
                "requested_squad": squad,
                "user_squad": current_user.display_name,
            },
        )
        flash("You do not have permission to access this squad.", "warning")
        return redirect(url_for("auth.login"))

    return None


@bp.route("/<squad>/admin-panel")
def admin_panel(squad: str) -> Any:
    return render_template(
        "admin_panel.html",
        squad=squad,
        contact_phone=current_app.config.get("CONTACT_PHONE", ""),
        panel_subtitle=f"{squad} inventory controls",
        admin=True,
    )


@bp.route("/<squad>/admin-panel/views")
def admin_panel_views(squad: str) -> Any:
    with get_session() as s:
        view_data = _admin_view_data(s, current_user.id)
    return render_template(
        "admin_panel_views.html",
        squad=squad,
        items=view_data["items"],
        locations=view_data["locations"],
        tags=view_data["tags"],
        admin=True,
        user_timezone=current_user.timezone,
        timezone_hint=get_timezone_hint(current_user.timezone),
    )


@ttl_cache(skip_first_args=1)
def _admin_view_data(session: Session, agency_id: int) -> dict[str, Any]:
    return {
        "items": list_items(agency_id, include_inactive=True, session=session),
        "locations": list(
            session.execute(
                select(AgencyLocations)
                .options(selectinload(AgencyLocations.storages))
                .where(AgencyLocations.agency_id == agency_id)
                .order_by(AgencyLocations.name)
            )
            .scalars()
            .all()
        ),
        "tags": list_tags(agency_id, session),
    }


@bp.route("/<squad>/admin-panel/pending-upcs", methods=["GET", "POST"])
def pending_upcs(squad: str) -> Any:
    if request.method == "POST":
        return _save_pending_upc_review(squad)
    with get_session() as s:
        review_upcs = list_review_unknown_upcs(s, current_user.id)
        items = list_items(current_user.id, session=s)
    return render_template(
        "admin_pending_upcs.html",
        squad=squad,
        pending_upcs=[scan for scan in review_upcs if scan.status == UnknownUpcStatus.PENDING],
        ignored_upcs=[scan for scan in review_upcs if scan.status == UnknownUpcStatus.IGNORE],
        items=items,
        admin=True,
        user_timezone=current_user.timezone,
    )


def _save_pending_upc_review(squad: str) -> Any:
    unknown_upc_id = parse_optional_int(request.form.get("unknown_upc_id"))
    action = request.form.get("action", "")
    try:
        if unknown_upc_id is None:
            raise ValueError("Pending UPC not found.")
        with get_session() as s:
            if action == "resolve":
                item_id = parse_optional_int(request.form.get("item_id"))
                if item_id is None:
                    raise ValueError("Select an item.")
                resolve_unknown_upc(s, current_user.id, unknown_upc_id, item_id)
                flash("UPC linked to item.", "success")
            elif action == "ignore":
                ignore_unknown_upc(s, current_user.id, unknown_upc_id)
                flash("UPC ignored.", "success")
            elif action == "unignore":
                unignore_unknown_upc(s, current_user.id, unknown_upc_id)
                flash("UPC moved back to pending.", "success")
            elif action == "remove":
                remove_unknown_upc(s, current_user.id, unknown_upc_id)
                flash("UPC review canceled.", "success")
            else:
                raise ValueError("Choose a valid UPC review action.")
            s.commit()
    except ValueError as exc:
        flash(str(exc), "error")
    return redirect(url_for("admin.pending_upcs", squad=squad))


@bp.get("/<squad>/items/<int:item_id>/locations/<int:agency_location_id>/trend")
def item_trend_chart(squad: str, item_id: int, agency_location_id: int) -> Any:
    with get_session() as s:
        item = s.scalar(
            select(Items).where(
                Items.agency_id == current_user.id,
                Items.id == item_id,
            )
        )
        location = s.scalar(
            select(AgencyLocations).where(
                AgencyLocations.agency_id == current_user.id,
                AgencyLocations.id == agency_location_id,
            )
        )
        if item is None or location is None:
            return {"error": "Item or location not found."}, 404
        return build_item_trend_chart(s, current_user.id, item, location).model_dump(mode="json")


@bp.route("/<squad>/admin-panel/inventory-count-levels")
@bp.route("/<squad>/admin-panel/inventory-count-levels/<int:agency_location_id>")
def inventory_counts(squad: str, agency_location_id: int | None = None) -> Any:
    with get_session() as s:
        locations = list_top_locations(current_user.id, s)
        agency_emails = list(
            s.execute(select(AgencyEmails).where(AgencyEmails.agency_id == current_user.id).order_by(AgencyEmails.email)).scalars().all()
        )
        active_location = _active_location(locations, agency_location_id)
        active_tab = _inventory_count_tab(s, current_user.id, active_location.id) if active_location else {"inventory_data": [], "storages": []}

    return render_template(
        "admin_inventory_counts.html",
        squad=squad,
        locations=locations,
        active_location=active_location,
        inventory_data=active_tab["inventory_data"],
        storages=active_tab["storages"],
        agency_emails=agency_emails,
        active_location_id=active_location.id if active_location else None,
        admin=True,
    )


@bp.route("/<squad>/admin-panel/inventory-count-levels/email", methods=["POST"])
def send_inventory_counts_email(squad: str) -> Any:
    selected_ids = [int(value) for value in request.form.getlist("agency_email_ids") if value.isdigit()]
    with get_session() as s:
        sent, total = send_inventory_count_report(s, current_user.id, selected_ids)
    if total == 0:
        logger.warning("Inventory report email request rejected: no recipients were selected")
        flash("Select at least one email recipient.", "warning")
    elif sent == total:
        logger.info(
            "Inventory report email sent successfully",
            extra={"recipient_count": sent},
        )
        flash(f"Sent inventory report to {sent} email recipient(s).", "success")
    else:
        logger.error(
            "Inventory report email partially failed",
            extra={"sent": sent, "recipient_count": total},
        )
        flash(f"Sent {sent} of {total} inventory report email(s).", "error")
    return redirect(url_for("admin.inventory_counts", squad=squad))


def _inventory_count_tab(session, agency_id: int, agency_location_id: int) -> dict:
    items, storages, counts = build_location_count_rows(session, agency_id, agency_location_id)
    rows = []
    for item in items:
        row: dict = {"item": item, "storage_counts": {}, "storage_classes": {}, "total": 0}
        for storage in storages:
            count = counts.get((item.id, storage.id), 0)
            row["storage_counts"][storage.id] = count
            row["storage_classes"][storage.id] = get_inventory_level_class(count)
            row["total"] += count
        row["total_class"] = get_inventory_level_class(row["total"])
        rows.append(row)
    return {"inventory_data": rows, "storages": storages}


@bp.route("/<squad>/admin-panel/restock")
@bp.route("/<squad>/admin-panel/restock/<int:agency_location_id>")
def restock(squad: str, agency_location_id: int | None = None) -> Any:
    try:
        with get_session() as s:
            locations = list_top_locations(current_user.id, s)
            active_location = _active_location(locations, agency_location_id)
            restock_data = _restock_rows(s, current_user.id, active_location.id) if active_location else []
    except Exception:
        logger.exception(
            "Restock analysis page failed to load",
            extra={
                "agency_location_id": agency_location_id,
            },
        )
        flash("Error loading restock analysis.", "error")
        locations = []
        active_location = None
        restock_data = []

    return render_template(
        "admin_restock.html",
        squad=squad,
        locations=locations,
        active_location=active_location,
        restock_data=restock_data,
        active_location_id=active_location.id if active_location else None,
        admin=True,
    )


@ttl_cache(skip_first_args=1)
def _restock_rows(session, agency_id: int, agency_location_id: int) -> list[dict]:
    rows = BulkService.get_restock_analysis(session, agency_id, agency_location_id)
    for row in rows:
        row["order_class"] = get_order_quantity_class(row.get("order_amount"))
        row["days_class"] = get_days_until_low_class(row.get("days_until_stockout"))
        row.update(_restock_cell_classes(row))
    return rows


def _restock_cell_classes(row: dict) -> dict[str, str]:
    current_total = int(row.get("current_total") or 0)
    min_quantity = int(row.get("min_quantity") or 0)
    projected_total = int(row.get("projected_lead_time_total") or 0)
    classes = {"current_total_class": get_inventory_level_class(current_total)}

    if current_total <= 0:
        classes["current_total_class"] = "restock-critical"
    elif current_total <= min_quantity:
        classes["current_total_class"] = "restock-low"
        classes["min_quantity_class"] = "restock-low"

    if projected_total <= 0:
        classes["projected_total_class"] = "restock-projected-stockout"
    elif projected_total <= min_quantity:
        classes["projected_total_class"] = "restock-projected-low"
        classes.setdefault("min_quantity_class", "restock-projected-low")

    return classes


@bp.route("/<squad>/admin-panel/bulk-actions")
@bp.route("/<squad>/admin-panel/bulk-actions/<int:agency_location_id>")
def bulk_actions(squad: str, agency_location_id: int | None = None) -> Any:
    if agency_location_id is None:
        with get_session() as s:
            locations = list_top_locations(current_user.id, s)
        return render_template(
            "admin_select_location.html",
            squad=squad,
            locations=locations,
            endpoint="admin.bulk_actions",
            title="Bulk Action",
            admin=True,
        )

    with get_session() as s:
        summary = load_location_item_summary(s, current_user.id, agency_location_id)
    if summary is None:
        _log_bulk_location_missing(squad, agency_location_id)
        flash("Location not found.", "error")
        return redirect(url_for("admin.bulk_actions", squad=squad))
    return render_template(
        "admin_bulk_mode.html",
        squad=squad,
        location=summary.location,
        item_count=summary.item_count,
        admin=True,
    )


@bp.route(
    "/<squad>/admin-panel/bulk-actions/<int:agency_location_id>/items",
    methods=["GET", "POST"],
)
def bulk_select_items(squad: str, agency_location_id: int) -> Any:
    with get_session() as s:
        selection = load_location_item_selection(s, current_user.id, agency_location_id)
    if selection is None:
        _log_bulk_location_missing(squad, agency_location_id)
        flash("Location not found.", "error")
        return redirect(url_for("admin.bulk_actions", squad=squad))

    if request.method == "POST":
        item_ids = _selected_bulk_item_ids(request.form.getlist("item_ids"), selection.items)
        if not item_ids:
            logger.warning(
                "Bulk item selection rejected: no items were selected",
                extra={
                    "agency_location_id": agency_location_id,
                },
            )
            flash("Select at least one item.", "warning")
            return redirect(
                url_for(
                    "admin.bulk_select_items",
                    squad=squad,
                    agency_location_id=agency_location_id,
                )
            )
        return redirect(_bulk_edit_url(squad, agency_location_id, item_ids))

    return render_template(
        "admin_bulk_select_items.html",
        squad=squad,
        location=selection.location,
        items=selection.items,
        admin=True,
    )


@bp.route(
    "/<squad>/admin-panel/bulk-actions/<int:agency_location_id>/edit",
    methods=["GET", "POST"],
)
def bulk_edit(squad: str, agency_location_id: int) -> Any:
    with get_session() as s:
        grid = load_location_quantity_grid(s, current_user.id, agency_location_id)
        if grid is None:
            _log_bulk_location_missing(squad, agency_location_id)
            flash("Location not found.", "error")
            return redirect(url_for("admin.bulk_actions", squad=squad))

        item_ids = _selected_bulk_item_ids(
            request.values.getlist("item_ids") or request.values.get("item_ids", "").split(","),
            grid.items,
        )
        if item_ids:
            grid = LocationQuantityGrid(
                grid.location,
                [item for item in grid.items if item.id in item_ids],
                grid.storages,
                grid.quantities,
            )

        required = required_count_storage_ids(s, current_user.id, agency_location_id, grid.items)
        raw_counts = _quantity_values(request.form, "count_")
        raw_restocks = _quantity_values(request.form, "restock_")
        invalid_count_cells = _invalid_quantity_cells(raw_counts)
        invalid_restock_cells = _invalid_quantity_cells(raw_restocks)
        if request.method == "POST" and (invalid_count_cells or invalid_restock_cells):
            logger.warning(
                "Bulk action rejected: quantity values must be non-negative whole numbers",
                extra={
                    "agency_location_id": agency_location_id,
                    "item_count": len(item_ids) or len(grid.items),
                    "invalid_count_cell_count": len(invalid_count_cells),
                    "invalid_restock_cell_count": len(invalid_restock_cells),
                },
            )
            flash("Counts and restocks must be 0 or higher.", "warning")
            return _render_bulk_edit(
                squad,
                grid,
                required,
                raw_counts,
                raw_restocks,
                invalid_count_cells,
                invalid_restock_cells,
            )
        submitted_counts = _non_negative_quantities(raw_counts)
        submitted_restocks = _non_negative_quantities(raw_restocks)
        invalid_cells = _missing_required_count_cells(required, submitted_counts, submitted_restocks)
        if request.method == "POST" and invalid_cells:
            logger.warning(
                "Bulk action rejected: required count values are missing before restock",
                extra={
                    "agency_location_id": agency_location_id,
                    "item_count": len(item_ids) or len(grid.items),
                    "missing_count_cell_count": len(invalid_cells),
                },
            )
            flash("Count required before restocking highlighted items.", "warning")
            return _render_bulk_edit(
                squad,
                grid,
                required,
                submitted_counts,
                submitted_restocks,
                invalid_cells,
                set(),
            )
        if request.method == "POST":
            return _save_bulk_edit(
                s,
                squad,
                grid.location,
                _changed_bulk_counts(request.form, submitted_counts),
                submitted_restocks,
                item_ids,
            )

        return _render_bulk_edit(squad, grid, required)


def _render_bulk_edit(
    squad: str,
    grid,
    required: dict[int, set[int]],
    submitted_counts: Mapping[tuple[int, int], int | str] | None = None,
    submitted_restocks: Mapping[tuple[int, int], int | str] | None = None,
    invalid_cells: set[tuple[int, int]] | None = None,
    invalid_restock_cells: set[tuple[int, int]] | None = None,
) -> Any:
    return render_template(
        "admin_bulk_actions.html",
        squad=squad,
        location=grid.location,
        rows=_bulk_rows(
            grid.items,
            grid.storages,
            grid.quantities,
            required,
            submitted_counts or {},
            submitted_restocks or {},
            invalid_cells or set(),
            invalid_restock_cells or set(),
        ),
        storages=grid.storages,
        item_ids=[item.id for item in grid.items],
        stale_count_days=current_user.count_last_days,
        admin=True,
    )


def _save_bulk_edit(
    session,
    squad: str,
    location: AgencyLocations,
    counts: dict[tuple[int, int], int],
    restocks: dict[tuple[int, int], int],
    item_ids: set[int],
) -> Any:
    if not counts and not any(quantity > 0 for quantity in restocks.values()):
        flash("No count or restock changes entered.", "warning")
        return redirect(_bulk_edit_url(squad, location.id, item_ids))
    try:
        count_logs = save_bulk_location_count(session, current_user.id, location.id, counts) if counts else 0
        restock_logs = save_bulk_location_restock(session, current_user.id, location.id, restocks) if restocks else 0
        session.commit()
        logger.info(
            "Bulk inventory changes saved",
            extra={
                "agency_location_id": location.id,
                "item_count": len(item_ids) or None,
                "count_entry_count": count_logs,
                "restock_entry_count": restock_logs,
                "entry_count": count_logs + restock_logs,
            },
        )
        flash(
            f"Saved {count_logs} count and {restock_logs} restock entries for {location.name}.",
            "success",
        )
        return redirect(url_for("admin.admin_panel", squad=squad))
    except Exception:
        session.rollback()
        logger.exception(
            "Bulk inventory changes could not be saved",
            extra={
                "agency_location_id": location.id,
                "item_count": len(item_ids) or None,
                "count_entry_count": len(counts),
                "restock_entry_count": sum(1 for quantity in restocks.values() if quantity > 0),
            },
        )
        flash("Could not save bulk action. Please try again.", "error")
        return redirect(_bulk_edit_url(squad, location.id, item_ids))


def _bulk_rows(
    items,
    storages,
    counts: dict[tuple[int, int], int],
    required: dict[int, set[int]],
    submitted_counts: Mapping[tuple[int, int], int | str],
    submitted_restocks: Mapping[tuple[int, int], int | str],
    invalid_cells: set[tuple[int, int]],
    invalid_restock_cells: set[tuple[int, int]],
) -> list[dict[str, Any]]:
    rows = []
    for item in items:
        cells = []
        for storage in storages:
            key = (item.id, storage.id)
            count_required = storage.id in required.get(item.id, set())
            count_value = submitted_counts.get(key, "" if count_required else counts.get(key, 0))
            cells.append(
                {
                    "storage": storage,
                    "count_value": count_value,
                    "count_original": "" if count_required else counts.get(key, 0),
                    "restock_value": submitted_restocks.get(key, ""),
                    "count_required": count_required,
                    "invalid": key in invalid_cells,
                    "restock_invalid": key in invalid_restock_cells,
                }
            )
        rows.append({"item": item, "cells": cells})
    return rows


def _changed_bulk_counts(
    form,
    submitted_counts: dict[tuple[int, int], int],
) -> dict[tuple[int, int], int]:
    originals = parse_quantity_grid(form, prefix="count_original_", skip_blank=True)
    return {key: value for key, value in submitted_counts.items() if originals.get(key) != value}


def _quantity_values(form, prefix: str) -> dict[tuple[int, int], str]:
    values = {}
    for key, value in form.items():
        if not key.startswith(prefix) or value == "":
            continue
        try:
            item_id, storage_id = key.removeprefix(prefix).split("_", maxsplit=1)
            values[(int(item_id), int(storage_id))] = value
        except ValueError:
            continue
    return values


def _invalid_quantity_cells(values: dict[tuple[int, int], str]) -> set[tuple[int, int]]:
    invalid = set()
    for key, value in values.items():
        if not value.isdigit():
            invalid.add(key)
    return invalid


def _non_negative_quantities(values: dict[tuple[int, int], str]) -> dict[tuple[int, int], int]:
    return {key: int(value) for key, value in values.items()}


def _missing_required_count_cells(
    required: dict[int, set[int]],
    counts: dict[tuple[int, int], int],
    restocks: dict[tuple[int, int], int],
) -> set[tuple[int, int]]:
    restocked_item_ids = {item_id for (item_id, _), quantity in restocks.items() if quantity > 0}
    return {
        (item_id, storage_id) for item_id in restocked_item_ids for storage_id in required.get(item_id, set()) if (item_id, storage_id) not in counts
    }


def _selected_bulk_item_ids(raw_ids: list[str], items) -> set[int]:
    allowed = {item.id for item in items}
    values = (part.strip() for raw_id in raw_ids for part in raw_id.split(","))
    return {int(value) for value in values if value.isdigit() and int(value) in allowed}


def _bulk_edit_url(squad: str, agency_location_id: int, item_ids: set[int]) -> str:
    if item_ids:
        return url_for(
            "admin.bulk_edit",
            squad=squad,
            agency_location_id=agency_location_id,
            item_ids=",".join(str(item_id) for item_id in sorted(item_ids)),
        )
    return url_for("admin.bulk_edit", squad=squad, agency_location_id=agency_location_id)


def _log_bulk_location_missing(squad: str, agency_location_id: int) -> None:
    logger.error(
        "Bulk action rejected: requested location was not found",
        extra={"agency_location_id": agency_location_id},
    )


@bp.route("/<squad>/admin-panel/history")
@bp.route("/<squad>/admin-panel/history/<int:agency_location_id>")
def admin_history(squad: str, agency_location_id: int | None = None) -> Any:
    page = max(parse_optional_int(request.args.get("page")) or 1, 1)
    with get_session() as s:
        locations = list_top_locations(current_user.id, s)
        action_logs, has_next_page = _history_logs(s, agency_location_id, page, HISTORY_PAGE_SIZE)
    return render_template(
        "admin_history.html",
        squad=squad,
        locations=locations,
        action_logs=action_logs,
        active_location_id=agency_location_id,
        page=page,
        has_next_page=has_next_page,
        admin=True,
        user_timezone=current_user.timezone,
        timezone_hint=get_timezone_hint(current_user.timezone),
        today_date=_local_today(current_user.timezone).isoformat(),
    )


@bp.route("/<squad>/admin-panel/history/print")
@bp.route("/<squad>/admin-panel/history/<int:agency_location_id>/print")
def admin_history_print(squad: str, agency_location_id: int | None = None) -> Any:
    start_date = request.args.get("start_date", "")
    end_date = request.args.get("end_date", "")
    try:
        start_utc, end_utc = _history_date_bounds(start_date, end_date, current_user.timezone)
    except ValueError as exc:
        if request.headers.get("X-Requested-With") == "fetch":
            return str(exc), 400
        flash(str(exc), "error")
        return redirect(_history_url(squad, agency_location_id))
    with get_session() as s:
        locations = list_top_locations(current_user.id, s)
        agency = s.get(Agencies, current_user.id)
        active_location = _active_location(locations, agency_location_id) if agency_location_id else None
        action_logs, _ = _history_logs(s, agency_location_id, 1, HISTORY_PRINT_LIMIT, start_utc, end_utc)
    return render_template(
        "admin_history_print_partial.html",
        squad=squad,
        action_logs=action_logs,
        agency_name=agency.display_name if agency else squad,
        location_name=active_location.name if active_location else "All Locations",
        start_date=start_date,
        end_date=end_date,
        admin=True,
        user_timezone=current_user.timezone,
        timezone_hint=get_timezone_hint(current_user.timezone),
    )


def _history_logs(
    session,
    agency_location_id: int | None,
    page: int,
    page_size: int,
    start_utc: datetime | None = None,
    end_utc: datetime | None = None,
) -> tuple[list[ActionLogs], bool]:
    stmt = (
        select(ActionLogs)
        .options(
            joinedload(ActionLogs.item),
            joinedload(ActionLogs.from_location),
            joinedload(ActionLogs.to_location),
        )
        .where(ActionLogs.agency_id == current_user.id)
    )
    if agency_location_id is not None:
        storage_ids = [storage.id for storage in get_location_storages(session, current_user.id, agency_location_id)]
        stmt = stmt.where(
            or_(
                ActionLogs.from_location_id.in_(storage_ids),
                ActionLogs.to_location_id.in_(storage_ids),
            )
            if storage_ids
            else ActionLogs.id == -1
        )
    if start_utc is not None:
        stmt = stmt.where(ActionLogs.time_scanned >= start_utc)
    if end_utc is not None:
        stmt = stmt.where(ActionLogs.time_scanned < end_utc)
    rows = list(session.execute(stmt.order_by(ActionLogs.id.desc()).offset((page - 1) * page_size).limit(page_size + 1)).scalars().all())
    return rows[:page_size], len(rows) > page_size


def _history_url(squad: str, agency_location_id: int | None) -> str:
    if agency_location_id:
        return url_for("admin.admin_history", squad=squad, agency_location_id=agency_location_id)
    return url_for("admin.admin_history", squad=squad)


def _history_date_bounds(start_value: str, end_value: str, timezone: str) -> tuple[datetime | None, datetime | None]:
    start_date = _parse_history_date(start_value, "Start date")
    end_date = _parse_history_date(end_value, "End date")
    today = _local_today(timezone)
    if start_date and start_date > today:
        raise ValueError("Start date cannot be in the future.")
    if end_date and end_date > today:
        raise ValueError("End date cannot be in the future.")
    if start_date and end_date and start_date > end_date:
        raise ValueError("Start date must be before end date.")
    local_timezone = _timezone_or_utc(timezone)
    start_utc = _local_midnight_utc(start_date, local_timezone) if start_date else None
    end_utc = _local_midnight_utc(end_date + timedelta(days=1), local_timezone) if end_date else None
    return start_utc, end_utc


def _parse_history_date(value: str, label: str) -> date | None:
    if not value:
        return None
    if len(value) != 10:
        raise ValueError(f"{label} must use YYYY-MM-DD.")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{label} must be a valid date.") from exc


def _local_today(timezone: str) -> date:
    return datetime.now(_timezone_or_utc(timezone)).date()


def _local_midnight_utc(day: date, local_timezone: tzinfo) -> datetime:
    return datetime.combine(day, time.min, tzinfo=local_timezone).astimezone(UTC).replace(tzinfo=None)


def _timezone_or_utc(timezone: str) -> tzinfo:
    try:
        return ZoneInfo(timezone)
    except Exception:
        return UTC


def _active_location(locations: list[AgencyLocations], agency_location_id: int | None) -> AgencyLocations | None:
    if not locations:
        return None
    if agency_location_id is None:
        return locations[0]
    return next((location for location in locations if location.id == agency_location_id), locations[0])


@bp.route("/<squad>/settings", methods=["GET", "POST"])
def settings_page(squad: str) -> Any:
    if request.method == "POST":
        return _save_settings(squad)

    with get_session() as s:
        locations = list_top_locations(current_user.id, s)
        current_location_id = get_device_location_id(current_user.id, s)
        current_location = next((location for location in locations if location.id == current_location_id), None)
    return render_template(
        "admin_settings.html",
        squad=squad,
        contact_phone=current_app.config.get("CONTACT_PHONE", ""),
        locations=locations,
        current_location=current_location,
        admin=True,
    )


def _save_settings(squad: str) -> Any:
    token = current_device_token()
    try:
        location_id = parse_optional_int(request.form.get("agency_location_id"))
        if location_id is None:
            raise ValueError("Select a default device location.")
        with get_session() as s:
            agency = s.get(Agencies, current_user.id)
            if agency is None:
                raise ValueError("Agency not found.")
            save_device_location(current_user.id, token, location_id, s)
            agency.user_count_allow = request.form.get("user_count_allow") == "1"
            agency.user_restock_allow = request.form.get("user_restock_allow") == "1"
            agency.lead_time_days = _positive_setting("lead_time_days", "Lead Time Days")
            agency.count_last_days = _positive_setting("count_last_days", "Stale Count Days")
            agency.alert_rare_scan_days = _positive_setting("alert_rare_scan_days", "Rare Takeout Days")
            s.commit()
        logger.info(
            "Admin settings saved successfully",
            extra={"agency_location_id": location_id},
        )
        flash("Settings saved.", "success")
        response = make_response(redirect(url_for("admin.admin_panel", squad=squad)))
        set_device_cookie(response, token)
        return response
    except ValueError as exc:
        logger.warning(
            "Admin settings rejected",
            extra={"error": str(exc)},
        )
        flash(str(exc), "error")
    except Exception:
        logger.exception("Admin settings save failed unexpectedly")
        flash("Settings could not be saved. Please try again.", "error")
    response = make_response(redirect(url_for("admin.settings_page", squad=squad)))
    set_device_cookie(response, token)
    return response


def _positive_setting(field: str, label: str) -> int:
    try:
        value = int(request.form.get(field, ""))
    except ValueError as exc:
        raise ValueError(f"{label} must be a whole number.") from exc
    if value < 1:
        raise ValueError(f"{label} must be at least 1.")
    return value


@bp.route("/<squad>/admin-panel/scan-items", methods=["GET", "POST"])
def admin_scan_items(squad: str) -> Any:
    if request.method == "POST":
        return _save_admin_scan_route(squad)

    scan_route = _selected_admin_scan_route()
    if scan_route is None:
        return _render_admin_scan_setup(squad)

    if request.args.get("scan_error") == "not_found":
        has_unknown_upc = _record_unknown_upc_from_request(squad)
        logger.warning(
            "Admin scan search could not find the scanned barcode",
            extra={
                "from_storage_id": scan_route["from_location_id"],
                "to_storage_id": scan_route["to_location_id"],
            },
        )
        flash(UNKNOWN_UPC_REVIEW_MESSAGE if has_unknown_upc else "Item not found. Please try again.", "warning")
    with get_session() as s:
        items_payload = load_item_search_payload(
            s,
            current_user.id,
            include_inactive=True,
            order_by_last_accessed=True,
        )
    return render_template(
        "index.html",
        items_payload=items_payload,
        squad=squad,
        logo_img=current_user.image,
        admin=True,
        page_subtitle="Ready for barcode scan or item search",
        selected_scan_route=scan_route["label"],
        selected_from_location_label=scan_route["from_label"],
        selected_to_location_label=scan_route["to_label"],
        selected_from_location_id=scan_route["from_location_id"],
        selected_to_location_id=scan_route["to_location_id"],
        scan_item_url_base=url_for("admin.scan_item", squad=squad),
        scan_error_url=url_for(
            "admin.admin_scan_items",
            squad=squad,
            from_location_id=scan_route["from_location_id"],
            to_location_id=scan_route["to_location_id"],
            scan_error="not_found",
        ),
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
            "Unknown UPC scan ignored because the code was invalid",
            extra={"error": str(exc)},
        )
        return False


@bp.route("/<squad>/admin-panel/scan")
def admin_scan_start(squad: str) -> Any:
    return handle_scan_start(
        squad,
        parse_optional_int(request.args.get("item_id")),
        upc=request.args.get("upc"),
        is_admin=True,
    )


@bp.route("/<squad>/admin-panel/scan/storages", methods=["GET", "POST"])
def scan_storages(squad: str) -> Any:
    if request.method == "POST":
        return handle_scan_storages_post(squad, request.form, is_admin=True)
    item_id = parse_optional_int(request.args.get("item_id"))
    user_count_allow = request.args.get("user_count_allow", "true").lower() != "false"
    user_restock_allow = request.args.get("user_restock_allow", "true").lower() != "false"
    return handle_scan_storages_get(squad, item_id, user_count_allow, user_restock_allow, is_admin=True)


@bp.route("/<squad>/admin-panel/scan/item", methods=["GET", "POST"])
def scan_item(squad: str) -> Any:
    if request.method == "POST":
        return handle_scan_item_post(squad, request.form, is_admin=True)
    item_id = parse_optional_int(request.args.get("item_id"))
    from_location_id = parse_optional_int(request.args.get("from_location_id"))
    to_location_id = parse_optional_int(request.args.get("to_location_id"))
    user_count_allow = request.args.get("user_count_allow", "true").lower() != "false"
    user_restock_allow = request.args.get("user_restock_allow", "true").lower() != "false"
    if to_location_id is None and not user_count_allow and not user_restock_allow:
        to_location_id = -1
    return handle_scan_item_get(
        squad,
        item_id,
        from_location_id,
        to_location_id,
        user_count_allow,
        user_restock_allow,
        is_admin=True,
    )


def _render_admin_scan_setup(squad: str) -> Any:
    with get_session() as s:
        storage_choices = load_scan_storage_choices(current_user.id, True, s)
        from_locations = storage_choices.from_storages
        to_locations = storage_choices.to_storages

    if not from_locations:
        logger.error("Admin scan setup failed: no valid source storages are available")
        flash("No valid storages found. Please check your location setup.", "error")
        return redirect(url_for("admin.admin_panel", squad=squad))

    selected_from_id = parse_optional_int(request.args.get("from_location_id"))
    selected_to_id = parse_optional_int(request.args.get("to_location_id"))
    return render_template(
        "admin_scan_setup.html",
        squad=squad,
        from_locations=from_locations,
        to_locations=to_locations,
        selected_from_id=selected_from_id,
        selected_to_id=selected_to_id,
        setup_subtitle="Choose the FROM and TO locations for the next scans",
        admin=True,
    )


def _save_admin_scan_route(squad: str) -> Any:
    try:
        route_request = AdminScanRouteRequest.model_validate(request.form.to_dict())
    except ValidationError as exc:
        logger.warning(
            "Admin scan setup rejected: submitted route form data was invalid",
            extra={"error": str(exc)},
        )
        flash("Invalid form data. Please try again.", "error")
        return redirect(url_for("admin.admin_panel", squad=squad))

    if route_request.same_location_error == "1":
        logger.warning(
            "Admin scan setup rejected: source and destination combination is not allowed",
            extra={
                "from_storage_id": route_request.from_location_id,
                "to_storage_id": route_request.to_location_id,
            },
        )
        flash("Invalid storage combination.", "error")
        return redirect(
            url_for(
                "admin.admin_scan_items",
                squad=squad,
                from_location_id=route_request.from_location_id,
                to_location_id=route_request.to_location_id,
            )
        )

    if not _is_valid_admin_scan_route(route_request.from_location_id, route_request.to_location_id):
        logger.warning(
            "Admin scan setup rejected: selected route is not allowed",
            extra={
                "from_storage_id": route_request.from_location_id,
                "to_storage_id": route_request.to_location_id,
            },
        )
        flash("Please choose valid scan locations.", "error")
        return redirect(url_for("admin.admin_scan_items", squad=squad))

    return redirect(
        url_for(
            "admin.admin_scan_items",
            squad=squad,
            from_location_id=route_request.from_location_id,
            to_location_id=route_request.to_location_id,
        )
    )


def _selected_admin_scan_route() -> dict[str, int | str] | None:
    from_location_id = parse_optional_int(request.args.get("from_location_id"))
    to_location_id = parse_optional_int(request.args.get("to_location_id"))
    if not _is_valid_admin_scan_route(from_location_id, to_location_id):
        return None

    from_location = resolve_scan_location(from_location_id, current_user.id)
    to_location = resolve_scan_location(to_location_id, current_user.id, takeout_allowed=True)

    return {
        "from_location_id": from_location_id or 0,
        "to_location_id": to_location_id or 0,
        "from_label": format_scan_location_label(from_location, is_admin=True),
        "to_label": format_scan_location_label(to_location, is_admin=True, takeout_allowed=True),
        "label": format_scan_route_label(from_location, to_location, is_admin=True),
    }


def _is_valid_admin_scan_route(
    from_location_id: int | None,
    to_location_id: int | None,
) -> bool:
    permissions = ScanPermissions(count=True, restock=True)
    with get_session() as s:
        return is_scan_route_allowed(
            current_user.id,
            from_location_id,
            to_location_id,
            permissions,
            is_admin=True,
            session=s,
        )
