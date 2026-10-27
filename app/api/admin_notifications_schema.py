"""Request model for the notification recipient endpoints."""

from app.api.schema import LOCKED_INPUT
from app.inventory.admin_edit_schema import AdminNotificationForm


class NotificationRecipientRequest(AdminNotificationForm):
    """One whole recipient row: its delivery settings plus every alert and summary toggle."""

    model_config = LOCKED_INPUT
