"""Admin blueprint routes for inventory management."""

from typing import Any

from flask import current_app, flash, make_response, redirect, render_template, request, url_for
from flask_login import current_user
from loguru import logger
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.auth.device_locations import current_device_token, get_or_create_device, save_device_location, set_device_cookie
from app.auth.models import Agency
from app.auth.queries import list_top_locations
from app.inventory import admin_bp as bp
from app.inventory.admin_edit_service import save_admin_settings
from app.inventory.barcodes import upc_bars
from app.inventory.expiration_service import save_expiration_count_correction
from app.inventory.expiration_ui_service import (
    build_expiration_entry_groups,
    expiration_count_correction_specs,
    group_expiration_entries_by_item,
    hidden_form_fields,
    parse_expiration_allocations,
)
from app.inventory.item_queries import list_items
from app.inventory.pending_tasks_service import pending_task_summary
from app.shared.constants import ADMIN_TIMEOUT, SAVE_RETRY_MESSAGE
from app.shared.database import get_session
from app.shared.form_parsing import selected_int_ids
from app.shared.utils import (
    get_agency_id_from_request,
    is_static_request,
    validate_admin_session,
    validate_agency_access,
)
from app.shared.validators import parse_optional_int


@bp.before_request
def check_admin() -> Any:
    if is_static_request():
        return None

    agency_id = get_agency_id_from_request()
    if agency_id is None:
        return redirect(url_for("auth.login"))

    if not current_user.is_authenticated:
        logger.info("Admin route rejected: unauthenticated", extra={"agency_id": agency_id})
        flash("You must be logged in.", "warning")
        return redirect(url_for("auth.login"))

    for redirect_url in [
        validate_agency_access(agency_id),
        validate_admin_session(agency_id, ADMIN_TIMEOUT),
    ]:
        if redirect_url:
            return redirect(redirect_url)

    if current_user.id != agency_id:
        logger.warning(
            "Admin route rejected: agency mismatch",
            extra={"requested_agency_id": agency_id, "user_agency_id": current_user.id},
        )
        flash("You do not have access to this agency.", "warning")
        return redirect(url_for("auth.login"))

    return None


@bp.route("/<int:agency_id>/admin-panel")
def admin_panel(agency_id: int) -> Any:
    return render_template(
        "admin_panel.html",
        agency_id=agency_id,
        contact_phone=current_app.config.get("CONTACT_PHONE", ""),
        panel_subtitle="Inventory Controls",
        admin=True,
    )


@bp.route("/<int:agency_id>/admin-panel/pending-tasks")
def pending_tasks(agency_id: int) -> Any:
    with get_session() as s:
        tasks = pending_task_summary(s, current_user.id)
    return render_template(
        "admin_pending_tasks.html",
        agency_id=agency_id,
        tasks=tasks,
        admin=True,
    )


@bp.route("/<int:agency_id>/admin-panel/pending-tasks/expiration-dates", methods=["GET", "POST"])
def pending_expiration_dates(agency_id: int) -> Any:
    from app.alerts.alert_service import sync_expiration_alerts

    with get_session() as s:
        groups = build_expiration_entry_groups(s, current_user.id, expiration_count_correction_specs(s, current_user.id))
        if not groups:
            sync_expiration_alerts(s, agency_id=current_user.id)
            s.commit()
            flash("No missing expiration dates need review.", "info")
            return redirect(url_for("admin.pending_tasks", agency_id=agency_id))
        if request.method == "POST":
            try:
                allocations_by_key = parse_expiration_allocations(request.form, groups)
                for group in groups:
                    save_expiration_count_correction(
                        s,
                        current_user.id,
                        group.spec.item_id,
                        group.spec.storage_id,
                        allocations_by_key[group.spec.key],
                    )
                sync_expiration_alerts(s, agency_id=current_user.id)
                s.commit()
            except ValueError as exc:
                s.rollback()
                logger.info("Expiration correction rejected", extra={"agency_id": current_user.id, "error": str(exc)})
                flash(str(exc), "warning")
                return _render_pending_expiration_dates(agency_id, groups)
            logger.info(
                "Expiration counts corrected without inventory history",
                extra={"agency_id": current_user.id, "item_storage_pair_count": len(groups)},
            )
            flash(f"Saved expiration dates for {len(groups)} item/storage pair(s).", "success")
            return redirect(url_for("admin.pending_tasks", agency_id=agency_id))
        return _render_pending_expiration_dates(agency_id, groups)


def _render_pending_expiration_dates(agency_id: int, groups) -> Any:
    return render_template(
        "expiration_entry.html",
        agency_id=agency_id,
        groups=groups,
        item_groups=group_expiration_entries_by_item(groups),
        hidden_fields=hidden_form_fields(request.form),
        form_action=None,
        cancel_url=url_for("admin.pending_tasks", agency_id=agency_id),
        back_label="Back to Pending Tasks",
        show_bottom_cancel=False,
        show_recount_links=True,
        compact_entry=True,
        submit_label="Save Expiration Dates",
        page_title="Fix Missing Expiration Dates",
        page_subtitle="Enter the current expiration dates for each listed storage",
        admin=True,
    )


@bp.route("/<int:agency_id>/admin-panel/print-labels", methods=["GET", "POST"])
def print_labels(agency_id: int) -> Any:
    with get_session() as s:
        items = list_items(current_user.id, session=s)
    if request.method == "POST":
        item_ids = set() if request.form.get("action") == "all" else _selected_item_ids(request.form.getlist("item_ids"), items)
        if request.form.get("action") != "all" and not item_ids:
            logger.info("Print labels rejected: no items selected", extra={"action": request.form.get("action")})
            flash("Select at least one item.", "warning")
            return redirect(url_for("admin.print_labels", agency_id=agency_id))
        return redirect(url_for("admin.print_label_preview", agency_id=agency_id, item_ids=",".join(str(item_id) for item_id in sorted(item_ids))))
    return render_template("admin_print_label_select.html", agency_id=agency_id, items=items, admin=True)


@bp.route("/<int:agency_id>/admin-panel/print-labels/preview", methods=["GET"])
def print_label_preview(agency_id: int) -> Any:
    with get_session() as s:
        items = list_items(current_user.id, session=s)
    item_ids = _selected_item_ids(request.args.getlist("item_ids"), items)
    selected = [item for item in items if not item_ids or item.id in item_ids]
    labels = [{"item": item, "upc": item.upc, "bars": upc_bars(item.upc)} for item in selected]
    return render_template(
        "admin_print_label_preview.html",
        agency_id=agency_id,
        labels=labels,
        logo_img=current_user.image,
        admin=True,
    )


def _selected_item_ids(raw_ids: list[str], items) -> set[int]:
    return selected_int_ids(raw_ids, {item.id for item in items})


@bp.route("/<int:agency_id>/settings", methods=["GET", "POST"])
def settings_page(agency_id: int) -> Any:
    if request.method == "POST":
        return _save_settings(agency_id)

    return _render_settings_page(agency_id)


def _render_settings_page(agency_id: int) -> Any:
    token = current_device_token()
    with get_session() as s:
        locations = list_top_locations(current_user.id, s)
        device = get_or_create_device(current_user.id, token, s)
        selected_location_id = device.agency_location_id
        s.commit()
    response = make_response(
        render_template(
            "admin_settings.html",
            agency_id=agency_id,
            contact_phone=current_app.config.get("CONTACT_PHONE", ""),
            locations=locations,
            selected_location_id=selected_location_id,
            admin=True,
        )
    )
    set_device_cookie(response, token)
    return response


def _save_settings(agency_id: int) -> Any:
    token = current_device_token()
    try:
        with get_session() as s:
            agency = s.get(Agency, current_user.id)
            if agency is None:
                raise ValueError("Agency not found.")
            settings_changed = save_admin_settings(s, agency, request.form.to_dict())
            device_changed = _save_device_default_location(s, token)
            changed = settings_changed or device_changed
            flash("Saved settings." if changed else "No settings changes entered.", "success" if changed else "info")
            s.commit()
        response = make_response(redirect(url_for("admin.settings_page", agency_id=agency_id)))
        set_device_cookie(response, token)
        return response
    except (ValueError, ValidationError) as exc:
        logger.warning(
            "Admin settings validation reached backend",
            extra={"error": str(exc)},
        )
        flash(SAVE_RETRY_MESSAGE, "error")
    except Exception:
        logger.exception("Admin settings save failed unexpectedly", extra={"agency_id": agency_id})
        flash(SAVE_RETRY_MESSAGE, "error")
    response = make_response(redirect(url_for("admin.settings_page", agency_id=agency_id)))
    set_device_cookie(response, token)
    return response


def _save_device_default_location(session: Session, token: str) -> bool:
    device = get_or_create_device(current_user.id, token, session)
    location_id = parse_optional_int(request.form.get("device_location_id"))
    if device.agency_location_id == location_id:
        return False
    save_device_location(current_user.id, token, location_id, session)
    logger.info(
        "Admin settings changed device default location",
        extra={"agency_id": current_user.id, "agency_location_id": location_id},
    )
    return True
