"""Admin blueprint routes for inventory management."""

from typing import Any

from flask import current_app, flash, make_response, redirect, render_template, request, url_for
from flask_login import current_user
from loguru import logger
from sqlalchemy import or_, select

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
    empty_quantity_grid,
    item_names_requiring_count,
    load_location_quantity_grid,
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
from app.inventory.search_payload import build_item_search_payload
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
        admin=True,
    )


@bp.route("/<squad>/admin-panel/views")
def admin_panel_views(squad: str) -> Any:
    with get_session() as s:
        items = list_items(current_user.id, include_inactive=True, session=s)
        locations = list_top_locations(current_user.id, session=s)
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
            s.execute(
                select(AgencyEmails)
                .where(AgencyEmails.agency_id == current_user.id)
                .order_by(AgencyEmails.email)
            )
            .scalars()
            .all()
        )
        location_tabs = [
            {
                "location": location,
                **_inventory_count_tab(s, current_user.id, location.id),
            }
            for location in locations
        ]

    return render_template(
        "admin_inventory_counts.html",
        squad=squad,
        location_tabs=location_tabs,
        agency_emails=agency_emails,
        active_location_id=agency_location_id,
        admin=True,
    )


@bp.route("/<squad>/admin-panel/inventory-count-levels/email", methods=["POST"])
def send_inventory_counts_email(squad: str) -> Any:
    selected_ids = [
        int(value) for value in request.form.getlist("agency_email_ids") if value.isdigit()
    ]
    with get_session() as s:
        sent, total = send_inventory_count_report(s, current_user.id, selected_ids)
    if total == 0:
        logger.warning(
            "Inventory report email rejected: no recipients",
            extra={"agency_id": current_user.id},
        )
        flash("Select at least one email recipient.", "warning")
    elif sent == total:
        logger.info(
            "Inventory report email sent",
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
            location_tabs = [
                {
                    "location": location,
                    "restock_data": _restock_rows(s, current_user.id, location.id),
                }
                for location in list_top_locations(current_user.id, s)
            ]
    except Exception:
        logger.exception(
            "Restock analysis failed",
            extra={
                "agency_id": current_user.id,
                "squad": squad,
                "agency_location_id": agency_location_id,
            },
        )
        flash("Error loading restock analysis.", "error")
        location_tabs = []

    return render_template(
        "admin_restock.html",
        squad=squad,
        location_tabs=location_tabs,
        active_location_id=agency_location_id,
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
        grid = load_location_quantity_grid(s, current_user.id, agency_location_id)
        if grid is None:
            logger.error(
                "Bulk action rejected: quantity grid unavailable",
                extra={
                    "agency_id": current_user.id,
                    "squad": squad,
                    "agency_location_id": agency_location_id,
                },
            )
            flash("Bulk action data not found.", "error")
            return redirect(url_for("admin.bulk_actions", squad=squad))
        location, items, storages = grid.location, grid.items, grid.storages
        counts = grid.quantities
        restock_values = empty_quantity_grid(items, storages)
        stale_items = item_names_requiring_count(s, current_user.id, agency_location_id, items)
    if location is None:
        logger.error(
            "Bulk action rejected: location not found",
            extra={
                "agency_id": current_user.id,
                "squad": squad,
                "agency_location_id": agency_location_id,
            },
        )
        flash("Location not found.", "error")
        return redirect(url_for("admin.bulk_actions", squad=squad))
    return render_template(
        "admin_bulk_actions.html",
        squad=squad,
        location=location,
        items=items,
        storages=storages,
        counts=counts,
        original_counts=dict(counts),
        restock_values=restock_values,
        original_restock_values=empty_quantity_grid(items, storages),
        stale_items=stale_items,
        stale_count_days=current_user.count_last_days,
        admin=True,
    )


@bp.route("/<squad>/admin-panel/count/<int:agency_location_id>", methods=["POST"])
def count_location(squad: str, agency_location_id: int) -> Any:
    with get_session() as s:
        grid = load_location_quantity_grid(s, current_user.id, agency_location_id)
        if grid is None:
            logger.error(
                "Bulk count rejected: location not found",
                extra={
                    "agency_id": current_user.id,
                    "squad": squad,
                    "agency_location_id": agency_location_id,
                },
            )
            flash("Location not found.", "error")
            return redirect(url_for("admin.admin_panel", squad=squad))
        location = grid.location
        counts = grid.quantities
        response = _handle_count_post(s, squad, location, counts)
        if response:
            return response
    return _bulk_actions_redirect(squad, agency_location_id)


@bp.route("/<squad>/admin-panel/restock/<int:agency_location_id>/receive", methods=["POST"])
def receive_location_restock(squad: str, agency_location_id: int) -> Any:
    with get_session() as s:
        grid = load_location_quantity_grid(s, current_user.id, agency_location_id)
        if grid is None:
            logger.error(
                "Bulk restock rejected: location not found",
                extra={
                    "agency_id": current_user.id,
                    "squad": squad,
                    "agency_location_id": agency_location_id,
                },
            )
            flash("Location not found.", "error")
            return redirect(url_for("admin.restock", squad=squad))
        location, items, storages = grid.location, grid.items, grid.storages
        values = empty_quantity_grid(items, storages)
        stale_items = item_names_requiring_count(s, current_user.id, agency_location_id, items)
        if stale_items:
            logger.warning(
                "Bulk restock blocked: full count required",
                extra={
                    "agency_id": current_user.id,
                    "squad": squad,
                    "agency_location_id": agency_location_id,
                    "stale_item_count": len(stale_items),
                },
            )
            flash("Full location count required before vendor restock.", "warning")
            return _bulk_actions_redirect(squad, agency_location_id)
        response = _handle_restock_post(s, squad, location, values)
        if response:
            return response
    return _bulk_actions_redirect(squad, agency_location_id)


def _handle_count_post(
    session,
    squad: str,
    location: AgencyLocations,
    counts: dict[tuple[int, int], int],
) -> Any | None:
    submitted_counts = parse_quantity_grid(request.form)
    try:
        count = save_bulk_location_count(
            session,
            current_user.id,
            location.id,
            submitted_counts,
        )
        session.commit()
        _log_bulk_save("Bulk count saved", squad, location.id, count)
        flash(f"Saved {count} count entries for {location.name}.", "success")
        return _bulk_actions_redirect(squad, location.id)
    except Exception:
        session.rollback()
        _log_bulk_failure("Bulk count failed", squad, location.id)
        flash("Could not save count. Your entered numbers are still shown.", "error")
        counts.update(submitted_counts)
        return None


def _handle_restock_post(
    session,
    squad: str,
    location: AgencyLocations,
    values: dict[tuple[int, int], int],
) -> Any | None:
    values.update(parse_quantity_grid(request.form))
    try:
        count = save_bulk_location_restock(
            session,
            current_user.id,
            location.id,
            values,
        )
        session.commit()
        _log_bulk_save("Bulk restock saved", squad, location.id, count)
        flash(f"Saved {count} restock entries for {location.name}.", "success")
        return _bulk_actions_redirect(squad, location.id)
    except Exception:
        session.rollback()
        _log_bulk_failure("Bulk restock failed", squad, location.id)
        flash("Could not save restock. Your entered numbers are still shown.", "error")
        return None


def _log_bulk_save(message: str, squad: str, agency_location_id: int, entry_count: int) -> None:
    logger.info(
        message,
        extra={
            "agency_id": current_user.id,
            "squad": squad,
            "agency_location_id": agency_location_id,
            "entry_count": entry_count,
        },
    )


def _log_bulk_failure(message: str, squad: str, agency_location_id: int) -> None:
    logger.exception(
        message,
        extra={
            "agency_id": current_user.id,
            "squad": squad,
            "agency_location_id": agency_location_id,
        },
    )


def _bulk_actions_redirect(squad: str, agency_location_id: int) -> Any:
    return redirect(
        url_for(
            "admin.bulk_actions",
            squad=squad,
            agency_location_id=agency_location_id,
        )
    )


# ---------------------------------------------------------------------------
# History and help
# ---------------------------------------------------------------------------


@bp.route("/<squad>/admin-panel/history")
@bp.route("/<squad>/admin-panel/history/<int:agency_location_id>")
def admin_history(squad: str, agency_location_id: int | None = None) -> Any:
    with get_session() as s:
        locations = list_top_locations(current_user.id, s)
        location_tabs: list[dict[str, Any]] = [
            {"location": None, "action_logs": _history_logs(s, None)}
        ]
        location_tabs.extend(
            {
                "location": location,
                "action_logs": _history_logs(s, location.id),
            }
            for location in locations
        )
    return render_template(
        "admin_history.html",
        squad=squad,
        location_tabs=location_tabs,
        active_location_id=agency_location_id,
        admin=True,
        user_timezone=current_user.timezone,
        timezone_hint=get_timezone_hint(current_user.timezone),
    )


def _history_logs(session, agency_location_id: int | None) -> list[ActionLogs]:
    stmt = select(ActionLogs).where(ActionLogs.agency_id == current_user.id)
    if agency_location_id is not None:
        storage_ids = [
            storage.id
            for storage in get_location_storages(session, current_user.id, agency_location_id)
        ]
        stmt = stmt.where(
            or_(
                ActionLogs.from_location_id.in_(storage_ids),
                ActionLogs.to_location_id.in_(storage_ids),
            )
            if storage_ids
            else ActionLogs.id == -1
        )
    return list(session.execute(stmt.order_by(ActionLogs.id.desc())).scalars().all())


@bp.route("/<squad>/settings", methods=["GET", "POST"])
def settings_page(squad: str) -> Any:
    if request.method == "POST":
        return _save_settings(squad)

    with get_session() as s:
        locations = list_top_locations(current_user.id, s)
        current_location_id = get_device_location_id(current_user.id, s)
        current_location = next(
            (location for location in locations if location.id == current_location_id), None
        )
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
            agency.alert_rare_scan_days = _positive_setting(
                "alert_rare_scan_days", "Rare Takeout Days"
            )
            s.commit()
        logger.info(
            "Admin settings saved",
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
            "Admin settings save failed",
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


@bp.route("/<squad>/admin-panel/scan-items")
def admin_scan_items(squad: str) -> Any:
    upc_error = request.args.get("upc_error")
    if upc_error:
        logger.error(
            "Admin inventory search failed: UPC not found",
            extra={"agency_id": current_user.id, "squad": squad, "upc": upc_error},
        )
        flash(f"UPC {upc_error} not found in inventory.", "error")
    with get_session() as s:
        items = list_items(
            current_user.id, include_inactive=True, order_by_last_accessed=True, session=s
        )
    return render_template(
        "index.html",
        items_payload=build_item_search_payload(items),
        squad=squad,
        logo_img=current_user.image,
        admin=True,
    )


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
    return handle_scan_storages_get(
        squad, item_id, user_count_allow, user_restock_allow, is_admin=True
    )


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
