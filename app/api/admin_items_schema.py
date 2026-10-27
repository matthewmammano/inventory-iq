"""Request models for the admin items, tags, and notification recipient endpoints."""

from app.api.schema import LOCKED_INPUT
from app.inventory.admin_edit_schema import AdminItemForm, AdminNotificationForm, AdminTagForm


class ItemRequest(AdminItemForm):
    """One whole item row as the admin editor submits it; every field is replaced, not merged."""

    model_config = LOCKED_INPUT


class TagRequest(AdminTagForm):
    """One whole tag row as the admin editor submits it."""

    model_config = LOCKED_INPUT


class NotificationRecipientRequest(AdminNotificationForm):
    """One whole recipient row: its delivery settings plus every alert and summary toggle."""

    model_config = LOCKED_INPUT
