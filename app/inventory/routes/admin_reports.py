"""Admin inventory report, restock, and history routes."""

from collections.abc import Mapping
from typing import Any

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user
from loguru import logger
from pydantic import ValidationError
from sqlalchemy import select

from app.auth.models import Agencies, AgencyLocations
from app.auth.queries import list_active_emails, list_top_locations
from app.inventory import admin_bp as bp
from app.inventory.history_service import HISTORY_REPORT_LIMIT, list_history_logs
from app.inventory.location_operations import build_location_count_rows
from app.inventory.models import Items
from app.inventory.report_email_service import send_history_report, send_inventory_count_report
from app.inventory.schema import HistoryDateRange, HistoryPageQuery
from app.inventory.ui import get_days_until_low_class, get_inventory_level_class, get_order_quantity_class
from app.prediction.bulk_service import BulkService
from app.prediction.history_service import build_item_trend_chart
from app.shared.cache import ttl_cache
from app.shared.database import get_session
from app.shared.form_parsing import selected_int_ids
from app.shared.validators import parse_optional_int

HISTORY_PAGE_SIZE = 50


@bp.route("/<squad>/items/<int:item_id>/locations/<int:agency_location_id>/trend", methods=["GET"])
def item_trend_chart(squad: str, item_id: int, agency_location_id: int) -> Any:
    with get_session() as s:
        item = s.scalar(select(Items).where(Items.agency_id == current_user.id, Items.id == item_id))
        location = s.scalar(select(AgencyLocations).where(AgencyLocations.agency_id == current_user.id, AgencyLocations.id == agency_location_id))
        if item is None or location is None:
            return {"error": "Item or location not found."}, 404
        return build_item_trend_chart(s, current_user.id, item, location).model_dump(mode="json")


@bp.route("/<squad>/admin-panel/inventory-count-levels")
@bp.route("/<squad>/admin-panel/inventory-count-levels/<int:agency_location_id>")
def inventory_counts(squad: str, agency_location_id: int | None = None) -> Any:
    with get_session() as s:
        locations = list_top_locations(current_user.id, s)
        agency_emails = list_active_emails(current_user.id, s)
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
    selected_ids = _selected_agency_email_ids(request.form.getlist("agency_email_ids"))
    active_location_id = parse_optional_int(request.form.get("active_location_id"))
    with get_session() as s:
        sent, total = send_inventory_count_report(s, current_user.id, selected_ids)
    _flash_email_delivery_result("Inventory report", sent, total, selected_count=len(selected_ids), log_name="Inventory report email")
    return redirect(_inventory_counts_url(squad, active_location_id))


@bp.route("/<squad>/admin-panel/inventory-count-levels/print")
@bp.route("/<squad>/admin-panel/inventory-count-levels/<int:agency_location_id>/print")
def inventory_counts_print(squad: str, agency_location_id: int | None = None) -> Any:
    with get_session() as s:
        locations = list_top_locations(current_user.id, s)
        active_location = _active_location(locations, agency_location_id)
        active_tab = _inventory_count_tab(s, current_user.id, active_location.id) if active_location else {"inventory_data": [], "storages": []}
    return render_template(
        "admin_inventory_counts_print_partial.html",
        squad=squad,
        location_name=active_location.name if active_location else "Inventory Report",
        inventory_data=active_tab["inventory_data"],
        storages=active_tab["storages"],
        admin=True,
    )


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


def _inventory_counts_url(squad: str, agency_location_id: int | None) -> str:
    if agency_location_id:
        return url_for("admin.inventory_counts", squad=squad, agency_location_id=agency_location_id)
    return url_for("admin.inventory_counts", squad=squad)


@bp.route("/<squad>/admin-panel/restock")
@bp.route("/<squad>/admin-panel/restock/<int:agency_location_id>")
def restock(squad: str, agency_location_id: int | None = None) -> Any:
    try:
        with get_session() as s:
            locations = list_top_locations(current_user.id, s)
            active_location = _active_location(locations, agency_location_id)
            restock_data = _restock_rows(s, current_user.id, active_location.id) if active_location else []
    except Exception:
        logger.exception("Restock analysis page failed to load", extra={"agency_location_id": agency_location_id})
        flash("Restock analysis could not load. Try again.", "error")
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


def _selected_agency_email_ids(raw_ids: list[str]) -> list[int]:
    return sorted(selected_int_ids(raw_ids))


def _flash_email_delivery_result(
    label: str,
    sent: int,
    total: int,
    *,
    selected_count: int,
    log_name: str,
) -> None:
    if total == 0:
        logger.info(f"{log_name} request rejected: no recipients selected", extra={"selected_recipient_count": selected_count})
        flash("Select at least one email recipient.", "warning")
        return
    if sent == total:
        logger.info(f"{log_name} sent successfully", extra={"recipient_count": sent})
        flash(f"Sent {label.lower()} to {sent} email recipient(s).", "success")
        return
    logger.error(f"{log_name} partially failed", extra={"sent": sent, "recipient_count": total})
    flash(f"Sent {sent} of {total} {label.lower()} email(s).", "error")


def _validation_message(exc: ValidationError) -> str:
    errors = exc.errors()
    if not errors:
        return "Invalid form data. Please try again."
    context = errors[0].get("ctx") or {}
    if "error" in context:
        return str(context["error"])
    return str(errors[0]["msg"])


def _history_date_range(
    values: Mapping[str, Any],
    *,
    timezone: str,
    agency_location_id: int | None,
    log_message: str,
) -> tuple[HistoryDateRange | None, str]:
    try:
        return HistoryDateRange.model_validate(dict(values) | {"timezone": timezone}), ""
    except ValidationError as exc:
        logger.info(
            log_message,
            extra={
                "agency_location_id": agency_location_id,
                "start_date": values.get("start_date", ""),
                "end_date": values.get("end_date", ""),
                "error": str(exc),
            },
        )
        return None, _validation_message(exc)


@bp.route("/<squad>/admin-panel/history")
@bp.route("/<squad>/admin-panel/history/<int:agency_location_id>")
def admin_history(squad: str, agency_location_id: int | None = None) -> Any:
    query = HistoryPageQuery.model_validate(request.args.to_dict())
    with get_session() as s:
        locations = list_top_locations(current_user.id, s)
        agency_emails = list_active_emails(current_user.id, s)
        active_location = _active_location(locations, agency_location_id) if agency_location_id else None
        action_logs, has_next_page = list_history_logs(s, current_user.id, agency_location_id, query.page_number, HISTORY_PAGE_SIZE)
    return render_template(
        "admin_history.html",
        squad=squad,
        locations=locations,
        agency_emails=agency_emails,
        action_logs=action_logs,
        active_location_id=agency_location_id,
        active_location_name=active_location.name if active_location else "All Locations",
        page=query.page_number,
        has_next_page=has_next_page,
        admin=True,
        user_timezone=current_user.timezone,
        today_date=HistoryDateRange(timezone=current_user.timezone).local_today.isoformat(),
    )


@bp.route("/<squad>/admin-panel/history/email", methods=["POST"])
def admin_history_email(squad: str) -> Any:
    agency_location_id = parse_optional_int(request.form.get("agency_location_id"))
    selected_ids = _selected_agency_email_ids(request.form.getlist("agency_email_ids"))
    date_range, error = _history_date_range(
        request.form.to_dict(),
        timezone=current_user.timezone,
        agency_location_id=agency_location_id,
        log_message="History email date range rejected",
    )
    if date_range is None:
        flash(error, "error")
        return redirect(_history_url(squad, agency_location_id))
    with get_session() as s:
        sent, total = send_history_report(
            s,
            current_user.id,
            selected_ids,
            agency_location_id,
            date_range.start_utc,
            date_range.end_utc,
            date_range.start_label,
            date_range.end_label,
        )
    _flash_email_delivery_result("History report", sent, total, selected_count=len(selected_ids), log_name="History report email")
    return redirect(_history_url(squad, agency_location_id))


@bp.route("/<squad>/admin-panel/history/print")
@bp.route("/<squad>/admin-panel/history/<int:agency_location_id>/print")
def admin_history_print(squad: str, agency_location_id: int | None = None) -> Any:
    date_range, error = _history_date_range(
        request.args.to_dict(),
        timezone=current_user.timezone,
        agency_location_id=agency_location_id,
        log_message="History print date range rejected",
    )
    if date_range is None:
        if request.headers.get("X-Requested-With") == "fetch":
            return error, 400
        flash(error, "error")
        return redirect(_history_url(squad, agency_location_id))
    with get_session() as s:
        locations = list_top_locations(current_user.id, s)
        agency = s.get(Agencies, current_user.id)
        active_location = _active_location(locations, agency_location_id) if agency_location_id else None
        action_logs, _ = list_history_logs(
            s,
            current_user.id,
            agency_location_id,
            1,
            HISTORY_REPORT_LIMIT,
            date_range.start_utc,
            date_range.end_utc,
        )
    return render_template(
        "admin_history_print_partial.html",
        squad=squad,
        action_logs=action_logs,
        agency_name=agency.display_name if agency else squad,
        location_name=active_location.name if active_location else "All Locations",
        start_date=date_range.start_label,
        end_date=date_range.end_label,
        admin=True,
        user_timezone=current_user.timezone,
    )


def _history_url(squad: str, agency_location_id: int | None) -> str:
    if agency_location_id:
        return url_for("admin.admin_history", squad=squad, agency_location_id=agency_location_id)
    return url_for("admin.admin_history", squad=squad)


def _active_location(locations: list[AgencyLocations], agency_location_id: int | None) -> AgencyLocations | None:
    if not locations:
        return None
    if agency_location_id is None:
        return locations[0]
    return next((location for location in locations if location.id == agency_location_id), locations[0])
