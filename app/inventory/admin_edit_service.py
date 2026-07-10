"""Admin data-edit services with explicit ownership checks."""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from loguru import logger
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.location_filters import validate_location_filter_ids
from app.auth.models import Agency, ItemTag, NotificationPreferenceSetting, NotificationRecipient
from app.auth.notification_preferences import (
    NOTIFICATION_FIELDS,
    PREFERENCE_BY_FIELD,
    AlertEmailFrequency,
)
from app.inventory.admin_edit_schema import AdminItemForm, AdminNotificationForm, AdminSettingsForm, AdminTagForm
from app.inventory.models import Item, ItemSecondaryUpc
from app.shared.email_client import EMAIL_RETRY_DELAYS_SECONDS, OutboundEmail, send_email
from app.shared.validators import parse_non_negative_int


def create_item(session: Session, agency_id: int, form: AdminItemForm) -> Item:
    from app.alerts.alert_service import generate_scheduled_alerts

    _validate_item_tags(session, agency_id, form.tag_ids)
    item = Item(agency_id=agency_id, active=True, last_accessed=None)
    session.add(item)
    _apply_model_values(item, form, exclude={"secondary_upcs"})
    _sync_secondary_upcs(session, agency_id, item, form.secondary_upcs)
    generate_scheduled_alerts(session, agency_id)
    logger.info("Admin item created", extra={"agency_id": agency_id})
    return item


def update_item(session: Session, agency_id: int, item_id: int, form: AdminItemForm) -> Item:
    from app.alerts.alert_service import generate_scheduled_alerts

    item = _get_owned_row(session, Item, agency_id, item_id, "Item")
    tags = _validate_item_tags(session, agency_id, form.tag_ids)
    form.tag_ids = sorted(set(form.tag_ids) | (set(item.tag_ids or []) - tags))
    upcs_changed = _secondary_upcs_changed(session, agency_id, item, form.secondary_upcs)
    fields_changed = _apply_model_values_if_changed(item, form, exclude={"secondary_upcs"})
    if upcs_changed:
        _sync_secondary_upcs(session, agency_id, item, form.secondary_upcs)
    if fields_changed or upcs_changed:
        generate_scheduled_alerts(session, agency_id)
    logger.info("Admin item updated", extra={"agency_id": agency_id, "item_id": item_id, "changed": fields_changed or upcs_changed})
    return item


def delete_item(session: Session, agency_id: int, item_id: int) -> Item:
    from app.alerts.alert_service import generate_scheduled_alerts

    item = _get_owned_row(session, Item, agency_id, item_id, "Item")
    item.active = False
    generate_scheduled_alerts(session, agency_id)
    logger.info("Admin item deleted", extra={"agency_id": agency_id, "item_id": item_id})
    return item


def create_tag(session: Session, agency_id: int, form: AdminTagForm) -> ItemTag:
    tag = _find_tag_by_name(session, agency_id, form.tag_name) or ItemTag(agency_id=agency_id)
    session.add(tag)
    _apply_model_values(tag, form)
    tag.active = True
    logger.info("Admin tag created", extra={"agency_id": agency_id})
    return tag


def update_tag(session: Session, agency_id: int, tag_id: int, form: AdminTagForm) -> ItemTag:
    tag = _get_owned_row(session, ItemTag, agency_id, tag_id, "Tag")
    changed = _apply_model_values_if_changed(tag, form)
    logger.info("Admin tag updated", extra={"agency_id": agency_id, "tag_id": tag_id, "changed": changed})
    return tag


def delete_tag(session: Session, agency_id: int, tag_id: int) -> ItemTag:
    tag = _get_owned_row(session, ItemTag, agency_id, tag_id, "Tag")
    tag.active = False
    logger.info("Admin tag deleted", extra={"agency_id": agency_id, "tag_id": tag_id})
    return tag


def create_notification(session: Session, agency_id: int, form: AdminNotificationForm) -> NotificationRecipient:
    location_ids = validate_location_filter_ids(session, agency_id, form.location_filter_ids)
    recipient = _find_recipient_by_email(session, agency_id, form.email) or NotificationRecipient(agency_id=agency_id)
    session.add(recipient)
    _apply_model_values(recipient, form, exclude={"location_filter_ids", *NOTIFICATION_FIELDS})
    recipient.active = True
    recipient.location_filter_ids = location_ids
    _sync_notification_preferences(recipient, form)
    logger.info("Admin notification recipient created", extra={"agency_id": agency_id})
    return recipient


def update_notification(session: Session, agency_id: int, recipient_id: int, form: AdminNotificationForm) -> NotificationRecipient:
    recipient = _get_owned_row(session, NotificationRecipient, agency_id, recipient_id, "Notification recipient")
    location_ids = validate_location_filter_ids(session, agency_id, form.location_filter_ids)
    changed = _apply_model_values_if_changed(recipient, form, exclude={"location_filter_ids", *NOTIFICATION_FIELDS})
    if recipient.location_filter_ids != location_ids:
        recipient.location_filter_ids = location_ids
        changed = True
    changed = _sync_notification_preferences(recipient, form) or changed
    logger.info("Admin notification recipient updated", extra={"agency_id": agency_id, "recipient_id": recipient_id, "changed": changed})
    return recipient


def delete_notification(session: Session, agency_id: int, recipient_id: int) -> NotificationRecipient:
    recipient = _get_owned_row(session, NotificationRecipient, agency_id, recipient_id, "Notification recipient")
    recipient.active = False
    logger.info("Admin notification recipient deleted", extra={"agency_id": agency_id, "recipient_id": recipient_id})
    return recipient


def save_admin_settings(session: Session, agency: Agency, values: dict[str, Any]) -> bool:
    from app.alerts.alert_service import generate_scheduled_alerts

    settings = AdminSettingsForm.model_validate(values)
    changed = _apply_model_values_if_changed(agency, settings, exclude={"pin"})
    if settings.pin and not agency.check_pin(settings.pin):
        agency.set_pin(settings.pin)
        changed = True
    if changed:
        generate_scheduled_alerts(session, agency.id)
    logger.info("Admin settings submitted", extra={"agency_id": agency.id, "changed": changed})
    return changed


def send_temporary_time_pin(session: Session, agency: Agency) -> bool:
    code = _local_time_code(agency.timezone)
    body = (
        "Inventory IQ temporary admin PIN\n\n"
        f"Your temporary admin PIN is: {code}\n\n"
        "This code is based on the current time. If you want this reset to a different number, contact support for a manual change."
    )
    sent = send_email(
        OutboundEmail(subject="Inventory IQ Temporary Admin PIN", text_body=body, to_email=agency.email),
        retry_delays_seconds=EMAIL_RETRY_DELAYS_SECONDS,
    )
    if not sent:
        logger.error("Temporary admin PIN email failed", extra={"agency_id": agency.id})
        return False
    agency.set_pin(code)
    logger.info("Temporary admin PIN set and emailed", extra={"agency_id": agency.id})
    return True


def item_form_values(form: Any) -> dict[str, Any]:
    """Build the AdminItemForm payload for one item from a single-item form post."""
    return {
        "name": form.get("name", "").strip(),
        "guest_quick_adjust": _checkbox_is_checked(form, "guest_quick_adjust"),
        "increments": _blank_to_none(form.get("increments")),
        "tag_ids": _submitted_int_list(form.getlist("tag_ids")),
        "image": _blank_to_none(form.get("image")),
        "expiration_tracking_enabled": _checkbox_is_checked(form, "expiration_tracking_enabled"),
        "expiration_notice_days_override": _blank_to_none(form.get("expiration_notice_days_override")),
        "min_quantity": form.get("min_quantity"),
        "max_quantity": form.get("max_quantity"),
        "batch_size": form.get("batch_size") or 1,
        "restock_delivery_days": _blank_to_none(form.get("restock_delivery_days")),
        "secondary_upcs": _submitted_secondary_upcs(form),
    }


def tag_form_values(form: Any) -> dict[str, Any]:
    """Build the AdminTagForm payload for one tag from a single-tag form post."""
    return {
        "tag_name": form.get("tag_name", "").strip(),
        "color": form.get("color", "").strip(),
    }


def notification_form_values(form: Any) -> dict[str, Any]:
    """Build the AdminNotificationForm payload for one recipient from a single-recipient form post."""
    return {
        "email": form.get("email", "").strip(),
        "location_filter_ids": _submitted_int_list(form.getlist("location_filter_ids")),
        "quiet_start_time": _blank_to_none(form.get("quiet_start_time")),
        "quiet_end_time": _blank_to_none(form.get("quiet_end_time")),
        "alert_frequency": form.get("alert_frequency") or AlertEmailFrequency.HOURLY,
    } | {field: _checkbox_is_checked(form, field) for field in NOTIFICATION_FIELDS}


def _sync_notification_preferences(recipient: NotificationRecipient, row: AdminNotificationForm) -> bool:
    existing = {preference.preference_key: preference for preference in recipient.preferences}
    changed = False
    for field in NOTIFICATION_FIELDS:
        preference = PREFERENCE_BY_FIELD[field]
        enabled = bool(getattr(row, field))
        setting = existing.get(preference.key)
        if setting is None:
            recipient.preferences.append(NotificationPreferenceSetting(preference_key=preference.key, enabled=enabled))
            changed = True
        elif setting.enabled != enabled:
            setting.enabled = enabled
            changed = True
    return changed


def _sync_secondary_upcs(session: Session, agency_id: int, item: Item, upcs: Sequence[str]) -> None:
    session.flush()
    rows = {
        row.upc: row
        for row in session.execute(
            select(ItemSecondaryUpc).where(ItemSecondaryUpc.agency_id == agency_id, ItemSecondaryUpc.item_id == item.id)
        ).scalars()
    }
    for upc, row in rows.items():
        row.active = upc in upcs
    for upc in upcs:
        secondary_upc = rows.get(upc)
        if secondary_upc is None:
            secondary_upc = session.scalar(select(ItemSecondaryUpc).where(ItemSecondaryUpc.agency_id == agency_id, ItemSecondaryUpc.upc == upc))
        if secondary_upc:
            if secondary_upc.item_id != item.id and secondary_upc.active:
                raise ValueError(f"UPC {upc} is already linked to another item.")
            secondary_upc.item_id = item.id
            secondary_upc.active = True
        else:
            session.add(ItemSecondaryUpc(agency_id=agency_id, item_id=item.id, upc=upc, active=True))


def _secondary_upcs_changed(session: Session, agency_id: int, item: Item, upcs: Sequence[str]) -> bool:
    if item.id is None:
        return bool(upcs)
    return set(_active_secondary_upcs(session, agency_id, item.id)) != set(upcs)


def _active_secondary_upcs(session: Session, agency_id: int, item_id: int) -> list[str]:
    return list(
        session.execute(
            select(ItemSecondaryUpc.upc).where(
                ItemSecondaryUpc.agency_id == agency_id,
                ItemSecondaryUpc.item_id == item_id,
                ItemSecondaryUpc.active.is_(True),
            )
        ).scalars()
    )


def _get_owned_row(session: Session, model_class: type[Any], agency_id: int, row_id: int, label: str) -> Any:
    row = session.get(model_class, row_id)
    if row is None or row.agency_id != agency_id:
        raise ValueError(f"{label} not found.")
    return row


def _validate_item_tags(session: Session, agency_id: int, tag_ids: list[int]) -> set[int]:
    active_tag_ids = set(session.execute(select(ItemTag.id).where(ItemTag.agency_id == agency_id, ItemTag.active.is_(True))).scalars())
    if invalid_tags := sorted(set(tag_ids) - active_tag_ids):
        raise ValueError(f"Invalid tag selection: {invalid_tags}")
    return active_tag_ids


def _find_tag_by_name(session: Session, agency_id: int, tag_name: str) -> ItemTag | None:
    return session.scalar(select(ItemTag).where(ItemTag.agency_id == agency_id, func.lower(ItemTag.tag_name) == tag_name.lower()))


def _find_recipient_by_email(session: Session, agency_id: int, email: str) -> NotificationRecipient | None:
    return session.scalar(
        select(NotificationRecipient).where(
            NotificationRecipient.agency_id == agency_id,
            NotificationRecipient.email == str(email),
        )
    )


def _apply_model_values(target: Any, source: BaseModel, *, exclude: set[str] | None = None) -> None:
    for key, value in source.model_dump(exclude=exclude or set()).items():
        setattr(target, key, value)


def _apply_model_values_if_changed(target: Any, source: BaseModel, *, exclude: set[str] | None = None) -> bool:
    values = source.model_dump(exclude=exclude or set())
    if not _has_model_value_changes(target, values):
        return False
    for key, value in values.items():
        setattr(target, key, value)
    return True


def _has_model_value_changes(target: Any, values: dict[str, Any]) -> bool:
    return any(_normalized_stored_value(target, key, value) != value for key, value in values.items())


def _normalized_stored_value(target: Any, key: str, submitted_value: Any) -> Any:
    stored_value = getattr(target, key)
    if isinstance(submitted_value, list):
        return sorted(stored_value or [])
    return stored_value


def _submitted_int_list(values: list[str]) -> list[int]:
    return [parsed for value in values if (parsed := parse_non_negative_int(value)) is not None]


def _checkbox_is_checked(form: Any, key: str) -> bool:
    return form.get(key) == "1"


def _blank_to_none(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


def _split_upcs(value: str) -> list[str]:
    return [part.strip() for raw in value.splitlines() for part in raw.split(",") if part.strip()]


def _submitted_secondary_upcs(form: Any) -> list[str]:
    values = form.getlist("secondary_upcs")
    if values:
        return [upc for value in values for upc in _split_upcs(value)]
    return _split_upcs(form.get("secondary_upcs", ""))


def _local_time_code(timezone: str) -> str:
    try:
        now = datetime.now(ZoneInfo(timezone))
    except Exception:
        now = datetime.now(UTC)
    return now.strftime("%H%M")
