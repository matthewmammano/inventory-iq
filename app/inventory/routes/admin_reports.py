"""Admin inventory report, restock, and history routes."""

from collections.abc import Mapping
from typing import Any

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user
from loguru import logger
from pydantic import ValidationError
from sqlalchemy import select

from app.auth.models import Agency, Location
from app.auth.queries import list_active_emails, list_top_locations
from app.inventory import admin_bp as bp
from app.inventory.count_page_service import InventoryCountPage, build_inventory_count_page
from app.inventory.history_service import HISTORY_REPORT_LIMIT, list_history_logs
from app.inventory.models import Item
from app.inventory.report_email_service import send_history_report, send_inventory_count_report, send_restock_report
from app.inventory.restock_page_service import RestockPageRow, build_restock_page_rows
from app.inventory.schema import HistoryDateRange, HistoryPageQuery
from app.prediction.history_service import build_item_trend_chart
from app.shared.cache import ttl_cache
from app.shared.database import get_session
from app.shared.form_parsing import selected_int_ids
from app.shared.validators import parse_optional_int

HISTORY_PAGE_SIZE = 50


@bp.route("/<squad>/items/<int:item_id>/locations/<int:agency_location_id>/trend", methods=["GET"])
def item_trend_chart(squad: str, item_id: int, agency_location_id: int) -> Any:
    with get_session() as s:
        item = s.scalar(select(Item).where(Item.agency_id == current_user.id, Item.id == item_id))
        location = s.scalar(select(Location).where(Location.agency_id == current_user.id, Location.id == agency_location_id))
        if item is None or location is None:
            return {"error": "Item or location not found."}, 404
        return build_item_trend_chart(s, current_user.id, item, location).model_dump(mode="json")


@bp.route("/<squad>/admin-panel/inventory-count-levels")
@bp.route("/<squad>/admin-panel/inventory-count-levels/<int:agency_location_id>")
def inventory_counts(squad: str, agency_location_id: int | None = None) -> Any:
    with get_session() as s:
        locations = list_top_locations(current_user.id, s)
        notification_recipients = list_active_emails(current_user.id, s)
        active_location = _active_location(locations, agency_location_id)
        active_tab = build_inventory_count_page(s, current_user.id, active_location.id) if active_location else InventoryCountPage([], [])

    return render_template(
        "admin_inventory_counts.html",
        squad=squad,
        locations=locations,
        active_location=active_location,
        inventory_data=active_tab.inventory_data,
        storages=active_tab.storages,
        notification_recipients=notification_recipients,
        active_location_id=active_location.id if active_location else None,
        admin=True,
    )


@bp.route("/<squad>/admin-panel/inventory-count-levels/email", methods=["POST"])
def send_inventory_counts_email(squad: str) -> Any:
    selected_ids = _selected_notification_recipient_ids(request.form.getlist("notification_recipient_ids"))
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
        active_tab = build_inventory_count_page(s, current_user.id, active_location.id) if active_location else InventoryCountPage([], [])
    return render_template(
        "admin_inventory_counts_print_partial.html",
        squad=squad,
        location_name=active_location.name if active_location else "Inventory Report",
        inventory_data=active_tab.inventory_data,
        storages=active_tab.storages,
        admin=True,
    )


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
            notification_recipients = list_active_emails(current_user.id, s)
            active_location = _active_location(locations, agency_location_id)
            restock_data = _restock_rows(s, current_user.id, active_location.id) if active_location else []
    except Exception:
        logger.exception("Restock analysis page failed to load", extra={"agency_location_id": agency_location_id})
        flash("Restock analysis could not load. Try again.", "error")
        locations = []
        notification_recipients = []
        active_location = None
        restock_data = []

    return render_template(
        "admin_restock.html",
        squad=squad,
        locations=locations,
        active_location=active_location,
        restock_data=restock_data,
        notification_recipients=notification_recipients,
        active_location_id=active_location.id if active_location else None,
        admin=True,
    )


@bp.route("/<squad>/admin-panel/restock/email", methods=["POST"])
def send_restock_email(squad: str) -> Any:
    selected_ids = _selected_notification_recipient_ids(request.form.getlist("notification_recipient_ids"))
    active_location_id = parse_optional_int(request.form.get("active_location_id"))
    with get_session() as s:
        sent, total = send_restock_report(s, current_user.id, selected_ids, active_location_id)
    _flash_email_delivery_result("Restock report", sent, total, selected_count=len(selected_ids), log_name="Restock report email")
    return redirect(_restock_url(squad, active_location_id))


@bp.route("/<squad>/admin-panel/restock/print")
@bp.route("/<squad>/admin-panel/restock/<int:agency_location_id>/print")
def restock_print(squad: str, agency_location_id: int | None = None) -> Any:
    with get_session() as s:
        locations = list_top_locations(current_user.id, s)
        active_location = _active_location(locations, agency_location_id)
        restock_data = _restock_rows(s, current_user.id, active_location.id) if active_location else []
    return render_template(
        "admin_restock_print_partial.html",
        squad=squad,
        location_name=active_location.name if active_location else "Restock Report",
        restock_data=restock_data,
        admin=True,
    )


@ttl_cache(skip_first_args=1)
def _restock_rows(session, agency_id: int, agency_location_id: int) -> list[RestockPageRow]:
    return build_restock_page_rows(session, agency_id, agency_location_id)


def _restock_url(squad: str, agency_location_id: int | None) -> str:
    if agency_location_id:
        return url_for("admin.restock", squad=squad, agency_location_id=agency_location_id)
    return url_for("admin.restock", squad=squad)


def _selected_notification_recipient_ids(raw_ids: list[str]) -> list[int]:
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
        notification_recipients = list_active_emails(current_user.id, s)
        active_location = _active_location(locations, agency_location_id) if agency_location_id else None
        action_logs, has_next_page = list_history_logs(s, current_user.id, agency_location_id, query.page_number, HISTORY_PAGE_SIZE)
    return render_template(
        "admin_history.html",
        squad=squad,
        locations=locations,
        notification_recipients=notification_recipients,
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
    selected_ids = _selected_notification_recipient_ids(request.form.getlist("notification_recipient_ids"))
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
        agency = s.get(Agency, current_user.id)
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


def _active_location(locations: list[Location], agency_location_id: int | None) -> Location | None:
    if not locations:
        return None
    if agency_location_id is None:
        return locations[0]
    return next((location for location in locations if location.id == agency_location_id), locations[0])
