"""Admin blueprint routes for inventory management."""

from typing import Any

from flask import current_app, flash, make_response, redirect, render_template, request, url_for
from flask_login import current_user
from loguru import logger
from pydantic import ValidationError
from sqlalchemy import or_, select
from sqlalchemy.orm import joinedload, selectinload

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
from app.inventory.item_queries import list_items
from app.inventory.location_operations import (
    build_location_count_rows,
    get_location_storages,
    parse_quantity_grid,
)
from app.inventory.models import ActionLogs
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
from app.prediction.bulk_service import BulkService
from app.shared.constants import ADMIN_TIMEOUT
from app.shared.database import get_session
from app.shared.timezone_utils import get_timezone_hint
from app.shared.utils import (
    get_squad_from_request,
    is_static_request,
    parse_optional_int,
    validate_admin_session,
    validate_squad_access,
)

HISTORY_PAGE_SIZE = 250

# ---------------------------------------------------------------------------
# Authorization guard
# ---------------------------------------------------------------------------


@bp.before_request
def check_admin() -> Any:
    if is_static_request():
        return None

    squad = get_squad_from_request() or ""
    if not current_user.is_authenticated:
        logger.warning("Admin route rejected: unauthenticated", extra={"squad": squad})
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
                "agency_id": current_user.id,
                "requested_squad": squad,
                "user_squad": current_user.display_name,
            },
        )
        flash("You do not have permission to access this squad.", "warning")
        return redirect(url_for("auth.login"))

    return None


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


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
        items = list_items(current_user.id, include_inactive=True, session=s)
        locations = list(
            s.execute(
                select(AgencyLocations)
                .options(selectinload(AgencyLocations.storages))
                .where(AgencyLocations.agency_id == current_user.id)
                .order_by(AgencyLocations.name)
            )
            .scalars()
            .all()
        )
        tags = list_tags(current_user.id, s)
    return render_template(
        "admin_panel_views.html",
        squad=squad,
        items=items,
        locations=locations,
        tags=tags,
        admin=True,
        user_timezone=current_user.timezone,
        timezone_hint=get_timezone_hint(current_user.timezone),
    )


# ---------------------------------------------------------------------------
# Inventory counts
# ---------------------------------------------------------------------------


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
        logger.warning(
            "Inventory report email request rejected: no recipients were selected",
            extra={"agency_id": current_user.id},
        )
        flash("Select at least one email recipient.", "warning")
    elif sent == total:
        logger.info(
            "Inventory report email sent successfully",
            extra={"agency_id": current_user.id, "recipient_count": sent},
        )
        flash(f"Sent inventory report to {sent} email recipient(s).", "success")
    else:
        logger.error(
            "Inventory report email partially failed",
            extra={"agency_id": current_user.id, "sent": sent, "recipient_count": total},
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


# ---------------------------------------------------------------------------
# Restock analysis
# ---------------------------------------------------------------------------


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
                "agency_id": current_user.id,
                "squad": squad,
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
                    "agency_id": current_user.id,
                    "squad": squad,
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
        submitted_counts = parse_quantity_grid(request.form, prefix="count_", skip_blank=True)
        submitted_restocks = parse_quantity_grid(request.form, prefix="restock_", skip_blank=True)
        invalid_cells = _missing_required_count_cells(required, submitted_counts, submitted_restocks)
        if request.method == "POST" and invalid_cells:
            logger.warning(
                "Bulk action rejected: required count values are missing before restock",
                extra={
                    "agency_id": current_user.id,
                    "squad": squad,
                    "agency_location_id": agency_location_id,
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
    submitted_counts: dict[tuple[int, int], int] | None = None,
    submitted_restocks: dict[tuple[int, int], int] | None = None,
    invalid_cells: set[tuple[int, int]] | None = None,
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
        _log_bulk_save("Bulk action saved", squad, location.id, count_logs + restock_logs)
        flash(
            f"Saved {count_logs} count and {restock_logs} restock entries for {location.name}.",
            "success",
        )
        return redirect(url_for("admin.admin_panel", squad=squad))
    except Exception:
        session.rollback()
        _log_bulk_failure("Bulk action failed", squad, location.id)
        flash("Could not save bulk action. Please try again.", "error")
        return redirect(_bulk_edit_url(squad, location.id, item_ids))


def _bulk_rows(
    items,
    storages,
    counts: dict[tuple[int, int], int],
    required: dict[int, set[int]],
    submitted_counts: dict[tuple[int, int], int],
    submitted_restocks: dict[tuple[int, int], int],
    invalid_cells: set[tuple[int, int]],
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


def _log_bulk_save(message: str, squad: str, agency_location_id: int, entry_count: int) -> None:
    logger.info(
        f"{message}: bulk inventory changes saved",
        extra={
            "agency_id": current_user.id,
            "squad": squad,
            "agency_location_id": agency_location_id,
            "entry_count": entry_count,
        },
    )


def _log_bulk_failure(message: str, squad: str, agency_location_id: int) -> None:
    logger.exception(
        f"{message}: bulk inventory changes could not be saved",
        extra={
            "agency_id": current_user.id,
            "squad": squad,
            "agency_location_id": agency_location_id,
        },
    )


def _log_bulk_location_missing(squad: str, agency_location_id: int) -> None:
    logger.error(
        "Bulk action rejected: requested location was not found",
        extra={
            "agency_id": current_user.id,
            "squad": squad,
            "agency_location_id": agency_location_id,
        },
    )


# ---------------------------------------------------------------------------
# History and help
# ---------------------------------------------------------------------------


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
    )


def _history_logs(
    session,
    agency_location_id: int | None,
    page: int,
    page_size: int,
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
    rows = list(session.execute(stmt.order_by(ActionLogs.id.desc()).offset((page - 1) * page_size).limit(page_size + 1)).scalars().all())
    return rows[:page_size], len(rows) > page_size


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
            extra={"agency_id": current_user.id, "squad": squad, "agency_location_id": location_id},
        )
        flash("Settings saved.", "success")
    except ValueError as exc:
        logger.warning(
            "Admin settings rejected",
            extra={"agency_id": current_user.id, "squad": squad, "error": str(exc)},
        )
        flash(str(exc), "error")
    except Exception:
        logger.exception(
            "Admin settings save failed unexpectedly",
            extra={"agency_id": current_user.id, "squad": squad},
        )
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


# ---------------------------------------------------------------------------
# Scan flow
# ---------------------------------------------------------------------------


@bp.route("/<squad>/admin-panel/scan-items", methods=["GET", "POST"])
def admin_scan_items(squad: str) -> Any:
    if request.method == "POST":
        return _save_admin_scan_route(squad)

    scan_route = _selected_admin_scan_route()
    if scan_route is None:
        return _render_admin_scan_setup(squad)

    if request.args.get("scan_error") == "not_found":
        logger.warning(
            "Admin scan search could not find the scanned barcode",
            extra={
                "agency_id": current_user.id,
                "squad": squad,
                "from_storage_id": scan_route["from_location_id"],
                "to_storage_id": scan_route["to_location_id"],
            },
        )
        flash("Item not found. Please try again.", "error")
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
        page_subtitle=scan_route["label"],
        selected_scan_route=scan_route["label"],
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


@bp.route("/<squad>/admin-panel/scan")
def admin_scan_start(squad: str) -> Any:
    return handle_scan_start(
        squad,
        parse_optional_int(request.args.get("item_id")),
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
        logger.error(
            "Admin scan setup failed: no valid source storages are available",
            extra={"agency_id": current_user.id, "squad": squad},
        )
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
            extra={"agency_id": current_user.id, "squad": squad, "error": str(exc)},
        )
        flash("Invalid form data. Please try again.", "error")
        return redirect(url_for("admin.admin_panel", squad=squad))

    if route_request.same_location_error == "1":
        logger.warning(
            "Admin scan setup rejected: source and destination combination is not allowed",
            extra={
                "agency_id": current_user.id,
                "squad": squad,
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
                "agency_id": current_user.id,
                "squad": squad,
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
