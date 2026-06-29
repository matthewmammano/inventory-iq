"""Admin data-edit services with explicit ownership checks."""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from loguru import logger
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.location_filters import validate_location_filter_ids
from app.auth.models import Agencies, AgencyEmails, AgencyItemTags
from app.auth.notification_preferences import (
    NOTIFICATION_FIELDS,
    NOTIFICATION_PREFERENCES,
)
from app.inventory.constants import UPC_GENERATION_PREFIX
from app.inventory.models import Items, ItemSecondaryUpc, validate_upc_code
from app.shared.email_client import EMAIL_RETRY_DELAYS_SECONDS, OutboundEmail, send_email
from app.shared.validation_types import (
    AdminPin,
    EmailAddress128,
    ImageSource,
    Increments,
    ItemName,
    NonNegativeFloat,
    OptionalPositiveInt,
    PositiveInt,
    QuietTime,
    TagColor,
    TagName,
)


class AdminItemForm(BaseModel):
    id: int | None = None
    name: ItemName
    active: bool = True
    guest_quick_adjust: bool = False
    increments: Increments = None
    tag_ids: list[int] = Field(default_factory=list)
    image: ImageSource = None
    min_quantity: PositiveInt
    max_quantity: PositiveInt
    batch_size: PositiveInt
    restock_delivery_days: OptionalPositiveInt = None
    prior_daily_usage: NonNegativeFloat
    secondary_upcs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_quantity_bounds(self):
        if self.max_quantity <= self.min_quantity:
            raise ValueError("Maximum quantity must be greater than minimum quantity.")
        return self

    @model_validator(mode="after")
    def validate_secondary_upcs(self):
        values = self.secondary_upcs
        normalized = [_validate_secondary_upc(value) for value in values if value]
        if len(normalized) != len(set(normalized)):
            raise ValueError("Secondary UPCs must be unique.")
        self.secondary_upcs = normalized
        return self


class AdminTagForm(BaseModel):
    id: int | None = None
    tag_name: TagName
    color: TagColor
    active: bool = True


class AdminNotificationFormBase(BaseModel):
    id: int | None = None
    email: EmailAddress128
    active: bool = True
    location_filter_ids: list[int] | None = None
    quiet_start_time: QuietTime = None
    quiet_end_time: QuietTime = None

    @model_validator(mode="after")
    def validate_quiet_hours_pair(self):
        if bool(self.quiet_start_time) != bool(self.quiet_end_time):
            raise ValueError("Quiet hours need both a start time and an end time.")
        return self


def _notification_default(field: str) -> bool:
    return next(preference.default for preference in NOTIFICATION_PREFERENCES if preference.field == field)


class AdminNotificationForm(AdminNotificationFormBase):
    alert_for_stockout: bool = _notification_default("alert_for_stockout")
    alert_for_stockout_pred: bool = _notification_default("alert_for_stockout_pred")
    alert_for_low: bool = _notification_default("alert_for_low")
    alert_for_low_pred: bool = _notification_default("alert_for_low_pred")
    alert_for_stale_count: bool = _notification_default("alert_for_stale_count")
    alert_for_rare_takeout: bool = _notification_default("alert_for_rare_takeout")
    alert_for_count: bool = _notification_default("alert_for_count")
    alert_for_restock: bool = _notification_default("alert_for_restock")
    alert_for_takeout: bool = _notification_default("alert_for_takeout")
    alert_for_transfer: bool = _notification_default("alert_for_transfer")
    daily_summary: bool = _notification_default("daily_summary")
    weekly_summary: bool = _notification_default("weekly_summary")
    monthly_summary: bool = _notification_default("monthly_summary")
    yearly_summary: bool = _notification_default("yearly_summary")


class AdminSettingsForm(BaseModel):
    image: ImageSource = None
    pin: AdminPin
    user_count_allow: bool = False
    user_restock_allow: bool = False
    lead_time_days: PositiveInt
    count_last_days: PositiveInt
    alert_rare_scan_days: PositiveInt


def save_admin_items(session: Session, agency_id: int, form: Any) -> int:
    from app.alerts.alert_service import generate_scheduled_alerts

    rows = _submitted_item_forms(form)
    tags = _active_tag_ids(session, agency_id)
    existing = _rows_by_id(session, Items, agency_id)
    changed = 0
    changed_item_ids: set[int] = set()
    for row in rows:
        active_tag_ids = set(row.tag_ids)
        if invalid_tags := sorted(active_tag_ids - tags):
            raise ValueError(f"Invalid tag selection: {invalid_tags}")
        item = existing.get(row.id) if row.id else Items(agency_id=agency_id, last_accessed=None)
        if item is None:
            raise ValueError("Item not found.")
        if row.id is None:
            session.add(item)
            _apply_model_values(item, row, exclude={"id", "secondary_upcs"})
            _sync_secondary_upcs(session, agency_id, item, row.secondary_upcs)
            changed += 1
            session.flush()
            changed_item_ids.add(item.id)
            continue
        row.tag_ids = sorted(active_tag_ids | (set(item.tag_ids or []) - tags))
        upcs_changed = _secondary_upcs_changed(session, agency_id, item, row.secondary_upcs)
        fields_changed = _apply_model_values_if_changed(item, row, exclude={"id", "secondary_upcs"})
        if upcs_changed:
            _sync_secondary_upcs(session, agency_id, item, row.secondary_upcs)
        if fields_changed or upcs_changed:
            changed += 1
            changed_item_ids.add(item.id)
    if changed_item_ids:
        generate_scheduled_alerts(session, agency_id)
    logger.info("Admin item edit submitted", extra={"agency_id": agency_id, "submitted_row_count": len(rows), "changed_row_count": changed})
    return changed


def save_admin_tags(session: Session, agency_id: int, form: Any) -> int:
    rows = _submitted_tag_forms(form)
    existing = _rows_by_id(session, AgencyItemTags, agency_id)
    changed = 0
    for row in rows:
        tag = (
            existing.get(row.id)
            if row.id
            else session.scalar(
                select(AgencyItemTags).where(
                    AgencyItemTags.agency_id == agency_id,
                    func.lower(AgencyItemTags.tag_name) == row.tag_name.lower(),
                )
            )
        )
        if tag is None:
            tag = AgencyItemTags(agency_id=agency_id)
            session.add(tag)
        if row.id is not None and tag.id != row.id:
            raise ValueError("Tag not found.")
        if _apply_model_values_if_changed(tag, row, exclude={"id"}):
            changed += 1
    logger.info("Admin tag edit submitted", extra={"agency_id": agency_id, "submitted_row_count": len(rows), "changed_row_count": changed})
    return changed


def save_admin_notifications(session: Session, agency_id: int, form: Any) -> int:
    rows = _submitted_notification_forms(form)
    existing = _rows_by_id(session, AgencyEmails, agency_id)
    changed = 0
    for row in rows:
        location_ids = validate_location_filter_ids(session, agency_id, row.location_filter_ids)
        recipient = (
            existing.get(row.id)
            if row.id
            else session.scalar(select(AgencyEmails).where(AgencyEmails.agency_id == agency_id, AgencyEmails.email == str(row.email)))
        )
        if recipient is None:
            recipient = AgencyEmails(agency_id=agency_id)
            session.add(recipient)
        if row.id is not None and recipient.id != row.id:
            raise ValueError("Notification recipient not found.")
        row_changed = _apply_model_values_if_changed(recipient, row, exclude={"id", "location_filter_ids"})
        if recipient.location_filter_ids != location_ids:
            recipient.location_filter_ids = location_ids
            row_changed = True
        if row_changed:
            changed += 1
    logger.info("Admin notification edit submitted", extra={"agency_id": agency_id, "submitted_row_count": len(rows), "changed_row_count": changed})
    return changed


def save_admin_settings(session: Session, agency: Agencies, values: dict[str, Any]) -> bool:
    from app.alerts.alert_service import generate_scheduled_alerts

    settings = AdminSettingsForm.model_validate(values)
    changed = _apply_model_values_if_changed(agency, settings)
    if changed:
        generate_scheduled_alerts(session, agency.id)
    logger.info("Admin settings submitted", extra={"agency_id": agency.id, "changed": changed})
    return changed


def _validate_secondary_upc(value: str) -> str:
    normalized = validate_upc_code(value)
    if normalized.startswith(UPC_GENERATION_PREFIX):
        raise ValueError("Secondary UPCs cannot use generated item UPCs.")
    return normalized


def send_temporary_time_pin(session: Session, agency: Agencies) -> bool:
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
    agency.pin = code
    logger.info("Temporary admin PIN set and emailed", extra={"agency_id": agency.id})
    return True


def _submitted_item_forms(form: Any) -> list[AdminItemForm]:
    rows = [
        AdminItemForm.model_validate(
            _submitted_row_values(form, f"item_{item_id}_") | {"id": item_id, "active": str(item_id) not in form.getlist("delete_item_ids")}
        )
        for item_id in _submitted_ids(form, "item_ids")
    ]
    if form.get("new_item_name", "").strip():
        rows.append(AdminItemForm.model_validate(_submitted_row_values(form, "new_item_") | {"active": True}))
    return rows


def _submitted_tag_forms(form: Any) -> list[AdminTagForm]:
    rows = [
        AdminTagForm.model_validate(
            _submitted_row_values(form, f"tag_{tag_id}_") | {"id": tag_id, "active": str(tag_id) not in form.getlist("delete_tag_ids")}
        )
        for tag_id in _submitted_ids(form, "tag_ids")
    ]
    if form.get("new_tag_tag_name", "").strip():
        rows.append(AdminTagForm.model_validate(_submitted_row_values(form, "new_tag_") | {"active": True}))
    return rows


def _submitted_notification_forms(form: Any) -> list[AdminNotificationForm]:
    rows = [
        AdminNotificationForm.model_validate(
            _submitted_row_values(form, f"email_{email_id}_")
            | {
                "id": email_id,
                "active": str(email_id) not in form.getlist("delete_email_ids"),
                "location_filter_ids": _submitted_optional_int_list(form.getlist(f"email_{email_id}_location_filter_ids")),
            }
        )
        for email_id in _submitted_ids(form, "email_ids")
    ]
    for prefix in form.getlist("new_email_keys") or ["new_email"]:
        if not form.get(f"{prefix}_email", "").strip():
            continue
        rows.append(
            AdminNotificationForm.model_validate(
                _submitted_row_values(form, f"{prefix}_")
                | {"active": True, "location_filter_ids": _submitted_optional_int_list(form.getlist(f"{prefix}_location_filter_ids"))}
            )
        )
    return rows


def _submitted_row_values(form: Any, prefix: str) -> dict[str, Any]:
    return {
        "name": form.get(f"{prefix}name", "").strip(),
        "tag_name": form.get(f"{prefix}tag_name", "").strip(),
        "email": form.get(f"{prefix}email", "").strip(),
        "color": form.get(f"{prefix}color", "").strip(),
        "guest_quick_adjust": _checkbox_is_checked(form, f"{prefix}guest_quick_adjust"),
        "increments": _blank_to_none(form.get(f"{prefix}increments")),
        "tag_ids": _submitted_int_list(form.getlist(f"{prefix}tag_ids")),
        "image": _blank_to_none(form.get(f"{prefix}image")),
        "min_quantity": form.get(f"{prefix}min_quantity"),
        "max_quantity": form.get(f"{prefix}max_quantity"),
        "batch_size": form.get(f"{prefix}batch_size") or 1,
        "restock_delivery_days": _blank_to_none(form.get(f"{prefix}restock_delivery_days")),
        "prior_daily_usage": form.get(f"{prefix}prior_daily_usage") or 0,
        "secondary_upcs": _submitted_secondary_upcs(form, prefix),
        "quiet_start_time": _blank_to_none(form.get(f"{prefix}quiet_start_time")),
        "quiet_end_time": _blank_to_none(form.get(f"{prefix}quiet_end_time")),
    } | {field: _checkbox_is_checked(form, f"{prefix}{field}") for field in NOTIFICATION_FIELDS}


def _sync_secondary_upcs(session: Session, agency_id: int, item: Items, upcs: Sequence[str]) -> None:
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


def _secondary_upcs_changed(session: Session, agency_id: int, item: Items, upcs: Sequence[str]) -> bool:
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


def _rows_by_id(session: Session, model_class, agency_id: int) -> dict[int, Any]:
    rows = session.execute(select(model_class).where(model_class.agency_id == agency_id)).scalars()
    return {row.id: row for row in rows}


def _active_tag_ids(session: Session, agency_id: int) -> set[int]:
    return set(session.execute(select(AgencyItemTags.id).where(AgencyItemTags.agency_id == agency_id, AgencyItemTags.active.is_(True))).scalars())


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


def _submitted_ids(form: Any, key: str) -> list[int]:
    return [int(value) for value in form.getlist(key) if str(value).isdigit()]


def _submitted_int_list(values: list[str]) -> list[int]:
    return [int(value) for value in values if str(value).isdigit()]


def _submitted_optional_int_list(values: list[str]) -> list[int] | None:
    ids = _submitted_int_list(values)
    return ids or None


def _checkbox_is_checked(form: Any, key: str) -> bool:
    return form.get(key) == "1"


def _blank_to_none(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


def _split_upcs(value: str) -> list[str]:
    return [part.strip() for raw in value.splitlines() for part in raw.split(",") if part.strip()]


def _submitted_secondary_upcs(form: Any, prefix: str) -> list[str]:
    values = form.getlist(f"{prefix}secondary_upcs")
    if values:
        return [upc for value in values for upc in _split_upcs(value)]
    return _split_upcs(form.get(f"{prefix}secondary_upcs", ""))


def _local_time_code(timezone: str) -> str:
    try:
        now = datetime.now(ZoneInfo(timezone))
    except Exception:
        now = datetime.now(UTC)
    return now.strftime("%H%M")
