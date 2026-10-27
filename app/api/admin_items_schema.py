"""Request models for the admin items and tags endpoints."""

from app.api.schema import LOCKED_INPUT
from app.inventory.admin_edit_schema import AdminItemForm, AdminTagForm


class ItemRequest(AdminItemForm):
    """One whole item row as the admin editor submits it; every field is replaced, not merged."""

    model_config = LOCKED_INPUT


class TagRequest(AdminTagForm):
    """One whole tag row as the admin editor submits it."""

    model_config = LOCKED_INPUT
