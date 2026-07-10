"""Merged view/edit admin data page: items, locations, tags, notifications.

Items, tags, and notification recipients are created/edited/deleted one row at a time
through per-row modals; see docs/CONVENTIONS.md "Single-Item Modal CRUD".
"""

from collections.abc import Callable
from typing import Any

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user
from loguru import logger
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.auth.models import Location
from app.auth.notification_preferences import ALERT_EMAIL_FREQUENCY_CHOICES, ALERT_NOTIFICATION_FIELDS, SUMMARY_NOTIFICATION_FIELDS
from app.auth.queries import list_active_emails, list_tags
from app.inventory import admin_bp as bp
from app.inventory.admin_edit_schema import AdminItemForm, AdminNotificationForm, AdminTagForm
from app.inventory.admin_edit_service import (
    create_item,
    create_notification,
    create_tag,
    delete_item,
    delete_notification,
    delete_tag,
    item_form_values,
    notification_form_values,
    tag_form_values,
    update_item,
    update_notification,
    update_tag,
)
from app.inventory.item_queries import list_items
from app.shared.constants import SAVE_RETRY_MESSAGE
from app.shared.database import get_session


@bp.route("/<squad>/admin-panel/data")
def admin_data(squad: str) -> Any:
    with get_session() as s:
        context = _admin_data_context(s, current_user.id)
    return render_template(
        "admin_data.html",
        squad=squad,
        active_tab=request.args.get("tab", "items"),
        alert_email_frequency_choices=ALERT_EMAIL_FREQUENCY_CHOICES,
        notification_alert_fields=ALERT_NOTIFICATION_FIELDS,
        notification_summary_fields=SUMMARY_NOTIFICATION_FIELDS,
        admin=True,
        user_timezone=current_user.timezone,
        **context,
    )


def _admin_data_context(session: Session, agency_id: int) -> dict[str, Any]:
    return {
        "items": list_items(agency_id, session=session),
        "locations": list(
            session.execute(select(Location).options(selectinload(Location.storages)).where(Location.agency_id == agency_id).order_by(Location.name))
            .scalars()
            .all()
        ),
        "tags": list_tags(agency_id, session),
        "notifications": list_active_emails(agency_id, session),
    }


def _redirect_to_tab(squad: str, tab: str) -> Any:
    return redirect(url_for("admin.admin_data", squad=squad, tab=tab))


@bp.route("/<squad>/admin-panel/data/items", methods=["POST"])
def admin_create_item(squad: str) -> Any:
    return _save_row(
        squad,
        "items",
        lambda item: f'Item "{item.name}" added.',
        lambda s: create_item(s, current_user.id, AdminItemForm.model_validate(item_form_values(request.form))),
    )


@bp.route("/<squad>/admin-panel/data/items/<int:item_id>", methods=["POST"])
def admin_update_item(squad: str, item_id: int) -> Any:
    return _save_row(
        squad,
        "items",
        lambda item: f'Item "{item.name}" saved.',
        lambda s: update_item(s, current_user.id, item_id, AdminItemForm.model_validate(item_form_values(request.form))),
    )


@bp.route("/<squad>/admin-panel/data/items/<int:item_id>/delete", methods=["POST"])
def admin_delete_item(squad: str, item_id: int) -> Any:
    return _save_row(squad, "items", lambda item: f'Item "{item.name}" removed.', lambda s: delete_item(s, current_user.id, item_id))


@bp.route("/<squad>/admin-panel/data/tags", methods=["POST"])
def admin_create_tag(squad: str) -> Any:
    return _save_row(
        squad,
        "tags",
        lambda tag: f'Tag "{tag.tag_name}" added.',
        lambda s: create_tag(s, current_user.id, AdminTagForm.model_validate(tag_form_values(request.form))),
    )


@bp.route("/<squad>/admin-panel/data/tags/<int:tag_id>", methods=["POST"])
def admin_update_tag(squad: str, tag_id: int) -> Any:
    return _save_row(
        squad,
        "tags",
        lambda tag: f'Tag "{tag.tag_name}" saved.',
        lambda s: update_tag(s, current_user.id, tag_id, AdminTagForm.model_validate(tag_form_values(request.form))),
    )


@bp.route("/<squad>/admin-panel/data/tags/<int:tag_id>/delete", methods=["POST"])
def admin_delete_tag(squad: str, tag_id: int) -> Any:
    return _save_row(squad, "tags", lambda tag: f'Tag "{tag.tag_name}" removed.', lambda s: delete_tag(s, current_user.id, tag_id))


@bp.route("/<squad>/admin-panel/data/notifications", methods=["POST"])
def admin_create_notification(squad: str) -> Any:
    return _save_row(
        squad,
        "notifications",
        lambda recipient: f'Notification "{recipient.email}" added.',
        lambda s: create_notification(s, current_user.id, AdminNotificationForm.model_validate(notification_form_values(request.form))),
    )


@bp.route("/<squad>/admin-panel/data/notifications/<int:recipient_id>", methods=["POST"])
def admin_update_notification(squad: str, recipient_id: int) -> Any:
    return _save_row(
        squad,
        "notifications",
        lambda recipient: f'Notification "{recipient.email}" saved.',
        lambda s: update_notification(s, current_user.id, recipient_id, AdminNotificationForm.model_validate(notification_form_values(request.form))),
    )


@bp.route("/<squad>/admin-panel/data/notifications/<int:recipient_id>/delete", methods=["POST"])
def admin_delete_notification(squad: str, recipient_id: int) -> Any:
    return _save_row(
        squad,
        "notifications",
        lambda recipient: f'Notification "{recipient.email}" removed.',
        lambda s: delete_notification(s, current_user.id, recipient_id),
    )


def _save_row(squad: str, tab: str, success_message: Callable[[Any], str], action: Callable[[Session], Any]) -> Any:
    try:
        with get_session() as s:
            result = action(s)
            s.commit()
        flash(success_message(result), "success")
    except (ValueError, ValidationError) as exc:
        logger.warning("Admin data save validation reached backend", extra={"tab": tab, "error": str(exc)})
        flash(SAVE_RETRY_MESSAGE, "error")
    except Exception:
        logger.exception("Admin data save failed unexpectedly", extra={"tab": tab})
        flash(SAVE_RETRY_MESSAGE, "error")
    return _redirect_to_tab(squad, tab)
