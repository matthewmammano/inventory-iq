"""Admin blueprint routes for inventory management."""

from typing import Any

from flask import current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user
from loguru import logger
from sqlalchemy import or_, select

from app.alerts.alert_service import record_action_log_alerts
from app.auth.queries import list_tags, list_top_locations
from app.inventory import admin_bp as bp
from app.inventory.item_queries import list_items
from app.inventory.location_operations import (
    build_location_count_rows,
    get_location_storages,
    parse_quantity_grid,
    save_location_count,
    save_location_restock,
)
from app.inventory.models import ActionLogs
from app.inventory.scan_flow import (
    handle_scan_item_get,
    handle_scan_item_post,
    handle_scan_start,
    handle_scan_storages_get,
    handle_scan_storages_post,
)
from app.inventory.ui import (
    get_days_until_low_class,
    get_inventory_level_class,
    get_order_quantity_class,
)
from app.prediction.bulk_service import BulkService
from app.prediction.estimator import get_location_item_quantity
from app.prediction.validation import validate_location_restock
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
    return render_template("admin_panel.html", squad=squad, admin=True)


@bp.route("/<squad>/admin-panel/views")
def admin_panel_views(squad: str) -> Any:
    return render_template("admin_panel_views.html", squad=squad, admin=True)


# ---------------------------------------------------------------------------
# Items
# ---------------------------------------------------------------------------


@bp.route("/<squad>/admin-panel/view-items")
def admin_view_items(squad: str) -> Any:
    with get_session() as s:
        items = list_items(current_user.id, include_inactive=True, session=s)
        tags = list_tags(current_user.id, s)
    return render_template(
        "admin_view_items.html",
        squad=squad,
        items=items,
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
    if agency_location_id is None:
        with get_session() as s:
            locations = list_top_locations(current_user.id, s)
        return render_template(
            "admin_select_location.html",
            squad=squad,
            locations=locations,
            endpoint="admin.inventory_counts",
            title="Inventory Count Levels",
            admin=True,
        )

    with get_session() as s:
        location = BulkService.get_location(s, current_user.id, agency_location_id)
        if location is None:
            logger.error(
                "Inventory counts rejected: location not found",
                extra={
                    "agency_id": current_user.id,
                    "squad": squad,
                    "agency_location_id": agency_location_id,
                },
            )
            flash("Location not found.", "error")
            return redirect(url_for("admin.inventory_counts", squad=squad))
        items, storages, counts = build_location_count_rows(s, current_user.id, agency_location_id)

    inventory_data = []
    for item in items:
        row: dict = {"item": item, "location_counts": {}, "location_classes": {}, "total": 0}
        for loc in storages:
            count = counts.get((item.id, loc.id), 0)
            row["location_counts"][loc.id] = count
            row["location_classes"][loc.id] = get_inventory_level_class(count)
            row["total"] += count
        row["total_class"] = get_inventory_level_class(row["total"])
        inventory_data.append(row)

    return render_template(
        "admin_inventory_counts.html",
        squad=squad,
        inventory_data=inventory_data,
        locations=storages,
        selected_location=location,
        admin=True,
    )


# ---------------------------------------------------------------------------
# Restock analysis
# ---------------------------------------------------------------------------


@bp.route("/<squad>/admin-panel/restock")
@bp.route("/<squad>/admin-panel/restock/<int:agency_location_id>")
def restock(squad: str, agency_location_id: int | None = None) -> Any:
    if agency_location_id is None:
        with get_session() as s:
            locations = list_top_locations(current_user.id, s)
        return render_template(
            "admin_select_location.html",
            squad=squad,
            locations=locations,
            endpoint="admin.restock",
            title="Restock Report",
            admin=True,
        )

    try:
        with get_session() as s:
            location = BulkService.get_location(s, current_user.id, agency_location_id)
            if location is None:
                logger.error(
                    "Restock report rejected: location not found",
                    extra={
                        "agency_id": current_user.id,
                        "squad": squad,
                        "agency_location_id": agency_location_id,
                    },
                )
                flash("Location not found.", "error")
                return redirect(url_for("admin.restock", squad=squad))
            restock_data = BulkService.get_restock_analysis(s, current_user.id, agency_location_id)
        for row in restock_data:
            row["order_class"] = get_order_quantity_class(row.get("order_amount"))
            row["current_total_class"] = get_inventory_level_class(row.get("current_total") or 0)
            row["days_class"] = get_days_until_low_class(row.get("days_until_stockout"))
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
        restock_data = []
        location = None

    return render_template(
        "admin_restock.html",
        squad=squad,
        restock_data=restock_data,
        selected_location=location,
        admin=True,
    )


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
        location = BulkService.get_location(s, current_user.id, agency_location_id)
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
    return render_template("admin_bulk_actions.html", squad=squad, location=location, admin=True)


@bp.route("/<squad>/admin-panel/count/<int:agency_location_id>", methods=["GET", "POST"])
def count_location(squad: str, agency_location_id: int) -> Any:
    with get_session() as s:
        location = BulkService.get_location(s, current_user.id, agency_location_id)
        if location is None:
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
        items, storages, counts = build_location_count_rows(s, current_user.id, agency_location_id)
        original_counts = dict(counts)
        if request.method == "POST":
            submitted_counts = parse_quantity_grid(request.form)
            try:
                quantity_snapshots = _location_item_snapshots(
                    s, current_user.id, agency_location_id, {item.id for item in items}
                )
                logs = save_location_count(s, current_user.id, agency_location_id, submitted_counts)
                count = len(logs)
                record_action_log_alerts(
                    s,
                    logs,
                    _updated_location_snapshots(
                        s, current_user.id, agency_location_id, quantity_snapshots
                    ),
                )
                s.commit()
                logger.info(
                    "Bulk count saved",
                    extra={
                        "agency_id": current_user.id,
                        "squad": squad,
                        "agency_location_id": agency_location_id,
                        "entry_count": count,
                    },
                )
                flash(f"Saved {count} count entries for {location.name}.", "success")
                return redirect(
                    url_for(
                        "admin.bulk_actions",
                        squad=squad,
                        agency_location_id=agency_location_id,
                    )
                )
            except Exception:
                s.rollback()
                logger.exception(
                    "Bulk count failed",
                    extra={
                        "agency_id": current_user.id,
                        "squad": squad,
                        "agency_location_id": agency_location_id,
                    },
                )
                flash("Could not save count. Your entered numbers are still shown.", "error")
                counts.update(submitted_counts)
    return render_template(
        "admin_location_count.html",
        squad=squad,
        location=location,
        items=items,
        storages=storages,
        counts=counts,
        original_counts=original_counts,
        admin=True,
    )


@bp.route("/<squad>/admin-panel/restock/<int:agency_location_id>/receive", methods=["GET", "POST"])
def receive_location_restock(squad: str, agency_location_id: int) -> Any:
    with get_session() as s:
        location = BulkService.get_location(s, current_user.id, agency_location_id)
        if location is None:
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
        items, storages, _counts = build_location_count_rows(s, current_user.id, agency_location_id)
        values = {(item.id, storage.id): 0 for item in items for storage in storages}
        stale_items = [
            item.name
            for item in items
            if not validate_location_restock(current_user.id, item.id, agency_location_id, s)[0]
        ]
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
            return redirect(
                url_for(
                    "admin.count_location",
                    squad=squad,
                    agency_location_id=agency_location_id,
                )
            )
        if request.method == "POST":
            values.update(parse_quantity_grid(request.form))
            try:
                quantity_snapshots = _location_item_snapshots(
                    s, current_user.id, agency_location_id, {item.id for item in items}
                )
                logs = save_location_restock(s, current_user.id, agency_location_id, values)
                count = len(logs)
                record_action_log_alerts(
                    s,
                    logs,
                    _updated_location_snapshots(
                        s, current_user.id, agency_location_id, quantity_snapshots
                    ),
                )
                s.commit()
                logger.info(
                    "Bulk restock saved",
                    extra={
                        "agency_id": current_user.id,
                        "squad": squad,
                        "agency_location_id": agency_location_id,
                        "entry_count": count,
                    },
                )
                flash(f"Saved {count} restock entries for {location.name}.", "success")
                return redirect(
                    url_for(
                        "admin.bulk_actions",
                        squad=squad,
                        agency_location_id=agency_location_id,
                    )
                )
            except Exception:
                s.rollback()
                logger.exception(
                    "Bulk restock failed",
                    extra={
                        "agency_id": current_user.id,
                        "squad": squad,
                        "agency_location_id": agency_location_id,
                    },
                )
                flash("Could not save restock. Your entered numbers are still shown.", "error")
    return render_template(
        "admin_location_restock_receive.html",
        squad=squad,
        location=location,
        items=items,
        storages=storages,
        values=values,
        original_values={(item.id, storage.id): 0 for item in items for storage in storages},
        admin=True,
    )


# ---------------------------------------------------------------------------
# Locations, tags, history, help
# ---------------------------------------------------------------------------


@bp.route("/<squad>/admin-panel/view-locations")
def admin_view_locations(squad: str) -> Any:
    with get_session() as s:
        locations = list_top_locations(current_user.id, session=s)
    return render_template(
        "admin_view_locations.html", squad=squad, locations=locations, admin=True
    )


@bp.route("/<squad>/admin-panel/view-tags")
def admin_view_tags(squad: str) -> Any:
    with get_session() as s:
        tags = list_tags(current_user.id, s)
    return render_template("admin_view_tags.html", squad=squad, tags=tags, admin=True)


@bp.route("/<squad>/admin-panel/history")
@bp.route("/<squad>/admin-panel/history/<int:agency_location_id>")
def admin_history(squad: str, agency_location_id: int | None = None) -> Any:
    if agency_location_id is None:
        with get_session() as s:
            locations = list_top_locations(current_user.id, s)
        return render_template(
            "admin_select_history_location.html", squad=squad, locations=locations, admin=True
        )

    selected_location = None
    with get_session() as s:
        stmt = select(ActionLogs).where(ActionLogs.agency_id == current_user.id)
        if agency_location_id != 0:
            selected_location = BulkService.get_location(s, current_user.id, agency_location_id)
            if selected_location is None:
                logger.error(
                    "History view rejected: location not found",
                    extra={
                        "agency_id": current_user.id,
                        "squad": squad,
                        "agency_location_id": agency_location_id,
                    },
                )
                flash("Location not found.", "error")
                return redirect(url_for("admin.admin_history", squad=squad))
            storage_ids = [
                storage.id
                for storage in get_location_storages(s, current_user.id, agency_location_id)
            ]
            stmt = stmt.where(
                or_(
                    ActionLogs.from_location_id.in_(storage_ids),
                    ActionLogs.to_location_id.in_(storage_ids),
                )
                if storage_ids
                else ActionLogs.id == -1
            )
        logs = list(s.execute(stmt.order_by(ActionLogs.id.desc())).scalars().all())
    return render_template(
        "admin_history.html",
        squad=squad,
        action_logs=logs,
        selected_location=selected_location,
        admin=True,
        user_timezone=current_user.timezone,
        timezone_hint=get_timezone_hint(current_user.timezone),
    )


@bp.route("/<squad>/help")
def help_page(squad: str) -> Any:
    return render_template(
        "admin_help.html",
        squad=squad,
        contact_phone=current_app.config.get("CONTACT_PHONE", ""),
        admin=True,
    )


def _location_item_snapshots(
    session,
    agency_id: int,
    agency_location_id: int,
    item_ids: set[int],
) -> dict[int, int]:
    return {
        item_id: get_location_item_quantity(session, agency_id, item_id, agency_location_id)
        for item_id in item_ids
    }


def _updated_location_snapshots(
    session,
    agency_id: int,
    agency_location_id: int,
    previous_totals: dict[int, int],
) -> dict[tuple[int, int, int], tuple[int, int]]:
    return {
        (agency_id, item_id, agency_location_id): (
            before_total,
            get_location_item_quantity(session, agency_id, item_id, agency_location_id),
        )
        for item_id, before_total in previous_totals.items()
    }


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
        "index.html", items=items, squad=squad, logo_img=current_user.image, admin=True
    )


@bp.route("/<squad>/admin-panel/scan")
def admin_scan_start(squad: str) -> Any:
    return handle_scan_start(squad, parse_optional_int(request.args.get("item_id")), is_admin=True)


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
