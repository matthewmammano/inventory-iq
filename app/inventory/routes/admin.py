"""Admin blueprint routes for inventory management."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from flask import current_app, flash, make_response, redirect, render_template, request, url_for
from flask_login import current_user
from loguru import logger
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.auth.device_locations import current_device_token, get_or_create_device, save_device_location, set_device_cookie
from app.auth.models import Agency, Location
from app.auth.notification_preferences import ALERT_EMAIL_FREQUENCY_CHOICES, ALERT_NOTIFICATION_FIELDS, SUMMARY_NOTIFICATION_FIELDS
from app.auth.queries import list_active_emails, list_tags, list_top_locations
from app.inventory import admin_bp as bp
from app.inventory.admin_edit_service import (
    save_admin_items,
    save_admin_notifications,
    save_admin_settings,
    save_admin_tags,
)
from app.inventory.barcodes import upc_bars
from app.inventory.constants import UnknownUpcStatus
from app.inventory.expiration_service import save_expiration_count_correction
from app.inventory.expiration_ui_service import (
    build_expiration_entry_groups,
    expiration_count_correction_specs,
    group_expiration_entries_by_item,
    hidden_form_fields,
    parse_expiration_allocations,
)
from app.inventory.item_queries import list_items
from app.inventory.models import UnknownUpcScan
from app.inventory.pending_tasks_service import pending_task_summary
from app.shared.constants import ADMIN_TIMEOUT
from app.shared.database import get_session
from app.shared.form_parsing import selected_int_ids
from app.shared.utils import (
    get_squad_from_request,
    is_static_request,
    validate_admin_session,
    validate_squad_access,
)
from app.shared.validators import parse_optional_int

SAVE_RETRY_MESSAGE = "Changes could not be saved. Review entries and try again."


@dataclass(frozen=True)
class AdminEditTabConfig:
    save: Callable[[Session, int, Any], int]
    row_label: str

    def flash_message(self, changed: int) -> str:
        return f"Saved {changed} {self.row_label} row(s)." if changed else f"No {self.row_label} changes entered."


EDIT_TAB_CONFIGS = {
    "items": AdminEditTabConfig(save_admin_items, "item"),
    "tags": AdminEditTabConfig(save_admin_tags, "tag"),
    "notifications": AdminEditTabConfig(save_admin_notifications, "notification setting"),
}


@bp.before_request
def check_admin() -> Any:
    if is_static_request():
        return None

    squad = get_squad_from_request() or ""
    if not current_user.is_authenticated:
        logger.info("Admin route rejected: unauthenticated", extra={"squad": squad})
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
        flash("You do not have access to this squad.", "warning")
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


@bp.route("/<squad>/admin-panel/pending-tasks")
def pending_tasks(squad: str) -> Any:
    with get_session() as s:
        tasks = pending_task_summary(s, current_user.id)
    return render_template(
        "admin_pending_tasks.html",
        squad=squad,
        tasks=tasks,
        admin=True,
    )


@bp.route("/<squad>/admin-panel/pending-tasks/expiration-dates", methods=["GET", "POST"])
def pending_expiration_dates(squad: str) -> Any:
    from app.alerts.alert_service import sync_expiration_alerts

    with get_session() as s:
        groups = build_expiration_entry_groups(s, current_user.id, expiration_count_correction_specs(s, current_user.id))
        if not groups:
            sync_expiration_alerts(s, agency_id=current_user.id)
            s.commit()
            flash("No missing expiration dates need review.", "info")
            return redirect(url_for("admin.pending_tasks", squad=squad))
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
                return _render_pending_expiration_dates(squad, groups)
            logger.info(
                "Expiration counts corrected without inventory history",
                extra={"agency_id": current_user.id, "item_storage_pair_count": len(groups)},
            )
            flash(f"Saved expiration dates for {len(groups)} item/storage pair(s).", "success")
            return redirect(url_for("admin.pending_tasks", squad=squad))
        return _render_pending_expiration_dates(squad, groups)


def _render_pending_expiration_dates(squad: str, groups) -> Any:
    return render_template(
        "expiration_entry.html",
        squad=squad,
        groups=groups,
        item_groups=group_expiration_entries_by_item(groups),
        hidden_fields=hidden_form_fields(request.form),
        form_action=None,
        cancel_url=url_for("admin.pending_tasks", squad=squad),
        back_label="Back to Pending Tasks",
        show_bottom_cancel=False,
        show_recount_links=True,
        compact_entry=True,
        submit_label="Save Expiration Dates",
        page_title="Fix Missing Expiration Dates",
        page_subtitle="Enter the current expiration dates for each listed storage",
        admin=True,
    )


@bp.route("/<squad>/admin-panel/edit-data", methods=["GET", "POST"])
def admin_edit_data(squad: str) -> Any:
    if request.method == "POST":
        return _save_admin_edit_data(squad)
    with get_session() as s:
        edit_data = _admin_edit_data(s, current_user.id)
    return render_template(
        "admin_edit_data.html",
        squad=squad,
        active_tab=request.args.get("tab", "items"),
        admin=True,
        **edit_data,
    )


def _save_admin_edit_data(squad: str) -> Any:
    tab = request.form.get("tab", "items")
    try:
        config = EDIT_TAB_CONFIGS.get(tab)
        if config is None:
            raise ValueError("Choose a valid edit tab.")
        with get_session() as s:
            changed = config.save(s, current_user.id, request.form)
            s.commit()
        flash(config.flash_message(changed), "success" if changed else "info")
        return redirect(url_for("admin.admin_panel", squad=squad))
    except (ValueError, ValidationError) as exc:
        logger.warning("Admin edit validation reached backend", extra={"tab": tab, "error": str(exc)})
        flash(SAVE_RETRY_MESSAGE, "error")
    except Exception:
        logger.exception("Admin edit save failed unexpectedly", extra={"tab": tab})
        flash(SAVE_RETRY_MESSAGE, "error")
    return redirect(url_for("admin.admin_edit_data", squad=squad, tab=tab))


def _admin_edit_data(session: Session, agency_id: int) -> dict[str, Any]:
    return {
        "items": list_items(agency_id, session=session),
        "tags": list_tags(agency_id, session),
        "locations": list_top_locations(agency_id, session),
        "notifications": list_active_emails(agency_id, session),
        "ignored_upcs": _ignored_upcs(session, agency_id),
        "alert_email_frequency_choices": ALERT_EMAIL_FREQUENCY_CHOICES,
        "notification_alert_fields": ALERT_NOTIFICATION_FIELDS,
        "notification_summary_fields": SUMMARY_NOTIFICATION_FIELDS,
    }


@bp.route("/<squad>/admin-panel/print-labels", methods=["GET", "POST"])
def print_labels(squad: str) -> Any:
    with get_session() as s:
        items = list_items(current_user.id, session=s)
    if request.method == "POST":
        item_ids = set() if request.form.get("action") == "all" else _selected_item_ids(request.form.getlist("item_ids"), items)
        if request.form.get("action") != "all" and not item_ids:
            logger.info("Print labels rejected: no items selected", extra={"action": request.form.get("action")})
            flash("Select at least one item.", "warning")
            return redirect(url_for("admin.print_labels", squad=squad))
        return redirect(url_for("admin.print_label_preview", squad=squad, item_ids=",".join(str(item_id) for item_id in sorted(item_ids))))
    return render_template("admin_print_label_select.html", squad=squad, items=items, admin=True)


@bp.route("/<squad>/admin-panel/print-labels/preview", methods=["GET"])
def print_label_preview(squad: str) -> Any:
    with get_session() as s:
        items = list_items(current_user.id, session=s)
    item_ids = _selected_item_ids(request.args.getlist("item_ids"), items)
    selected = [item for item in items if not item_ids or item.id in item_ids]
    labels = [{"item": item, "upc": item.upc, "bars": upc_bars(item.upc)} for item in selected]
    return render_template(
        "admin_print_label_preview.html",
        squad=squad,
        labels=labels,
        logo_img=current_user.image,
        admin=True,
    )


def _selected_item_ids(raw_ids: list[str], items) -> set[int]:
    return selected_int_ids(raw_ids, {item.id for item in items})


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
        notifications=view_data["notifications"],
        ignored_upcs=view_data["ignored_upcs"],
        notification_alert_fields=ALERT_NOTIFICATION_FIELDS,
        notification_summary_fields=SUMMARY_NOTIFICATION_FIELDS,
        admin=True,
        user_timezone=current_user.timezone,
    )


def _admin_view_data(session: Session, agency_id: int) -> dict[str, Any]:
    return {
        "items": list_items(agency_id, session=session),
        "locations": list(
            session.execute(select(Location).options(selectinload(Location.storages)).where(Location.agency_id == agency_id).order_by(Location.name))
            .scalars()
            .all()
        ),
        "tags": list_tags(agency_id, session),
        "notifications": list_active_emails(agency_id, session),
        "ignored_upcs": _ignored_upcs(session, agency_id),
    }


def _ignored_upcs(session: Session, agency_id: int) -> list[UnknownUpcScan]:
    return list(
        session.execute(
            select(UnknownUpcScan)
            .options(selectinload(UnknownUpcScan.suggested_item))
            .where(UnknownUpcScan.agency_id == agency_id, UnknownUpcScan.status == UnknownUpcStatus.IGNORE)
            .order_by(UnknownUpcScan.updated_at.desc(), UnknownUpcScan.id.desc())
        )
        .scalars()
        .all()
    )


@bp.route("/<squad>/settings", methods=["GET", "POST"])
def settings_page(squad: str) -> Any:
    if request.method == "POST":
        return _save_settings(squad)

    return _render_settings_page(squad)


def _render_settings_page(squad: str) -> Any:
    token = current_device_token()
    with get_session() as s:
        locations = list_top_locations(current_user.id, s)
        device = get_or_create_device(current_user.id, token, s)
        selected_location_id = device.agency_location_id
        s.commit()
    response = make_response(
        render_template(
            "admin_settings.html",
            squad=squad,
            contact_phone=current_app.config.get("CONTACT_PHONE", ""),
            locations=locations,
            selected_location_id=selected_location_id,
            admin=True,
        )
    )
    set_device_cookie(response, token)
    return response


def _save_settings(squad: str) -> Any:
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
        response = make_response(redirect(url_for("admin.settings_page", squad=squad)))
        set_device_cookie(response, token)
        return response
    except (ValueError, ValidationError) as exc:
        logger.warning(
            "Admin settings validation reached backend",
            extra={"error": str(exc)},
        )
        flash(SAVE_RETRY_MESSAGE, "error")
    except Exception:
        logger.exception("Admin settings save failed unexpectedly", extra={"squad": squad})
        flash(SAVE_RETRY_MESSAGE, "error")
    response = make_response(redirect(url_for("admin.settings_page", squad=squad)))
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
