"""Response models for the scan surface: items, storage choices, and a saved scan."""

from datetime import date

from pydantic import BaseModel, ConfigDict, RootModel

from app.auth.models import Storage
from app.auth.response import StorageResponse
from app.shared.image_paths import static_image_url

from .constants import OperationType
from .expiration_ui_service import ExpirationEntryGroup, ExpirationOption
from .models import Item
from .scan_hints import ScanHints
from .scan_submit_service import ScanSubmitResult
from .scan_support import ScanPermissions, ScanStorageChoices
from .search_payload import ItemSearchPayload


class ItemTagResponse(BaseModel):
    """A tag as the item row renders it."""

    name: str
    color: str
    text_color: str


class ItemResponse(BaseModel):
    """One searchable item. Name and tags only; the scan list shows no on-hand count."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    image_url: str
    upc: str
    upcs: list[str]
    last_accessed: str
    tags: list[ItemTagResponse]

    @classmethod
    def of(cls, payload: ItemSearchPayload) -> "ItemResponse":
        return cls(
            id=payload["id"],
            name=payload["name"],
            image_url=static_image_url(payload["image"]),
            upc=payload["upc"],
            upcs=payload["upcs"],
            last_accessed=payload["last_accessed"],
            tags=[ItemTagResponse(**tag) for tag in payload["tag_data"]],
        )


class ItemListResponse(RootModel[list[ItemResponse]]):
    """A page of searchable items."""


class ScanStorageOptionsResponse(BaseModel):
    """Where a scan may come from and go to, and what this scanner is allowed to do."""

    from_storages: list[StorageResponse]
    to_storages: list[StorageResponse]
    default_location_id: int | None
    can_count: bool
    can_restock: bool

    @classmethod
    def of(cls, choices: ScanStorageChoices, permissions: ScanPermissions) -> "ScanStorageOptionsResponse":
        return cls(
            from_storages=[StorageResponse.of(storage) for storage in choices.from_storages],
            to_storages=[StorageResponse.of(storage) for storage in choices.to_storages],
            default_location_id=choices.default_location_id,
            can_count=permissions.count,
            can_restock=permissions.restock,
        )


class ScanResultResponse(BaseModel):
    """What one saved scan did. The caller phrases its own confirmation from these facts."""

    operation: OperationType
    item_id: int
    item_name: str
    quantity: int
    from_storage: StorageResponse | None
    to_storage: StorageResponse | None
    initial_count_required: bool

    @classmethod
    def of(cls, result: ScanSubmitResult) -> "ScanResultResponse":
        return cls(
            operation=result.operation_type,
            item_id=result.item.id,
            item_name=result.item.name,
            quantity=result.quantity,
            from_storage=_storage_response(result.from_storage),
            to_storage=_storage_response(result.to_storage),
            initial_count_required=result.initial_count_required,
        )


def _storage_response(storage: Storage | int | None) -> StorageResponse | None:
    """RESTOCK, COUNT and TAKE arrive as virtual ids, not storages; the operation already names them."""
    return StorageResponse.of(storage) if isinstance(storage, Storage) else None


class ScanContextResponse(BaseModel):
    """Everything the quantity screen shows: the item, the route it is on, and its two hints."""

    item_id: int
    item_name: str
    image_url: str
    increments: str | None
    quick_adjust: bool
    expiration_tracking: bool
    operation: OperationType
    minimum_quantity: int
    from_label: str
    to_label: str
    stale_count: bool
    suggested_restock: int | None

    @classmethod
    def of(
        cls,
        item: Item,
        operation: OperationType,
        from_label: str,
        to_label: str,
        hints: ScanHints,
    ) -> "ScanContextResponse":
        return cls(
            item_id=item.id,
            item_name=item.name,
            image_url=static_image_url(item.image),
            increments=item.increments,
            quick_adjust=item.guest_quick_adjust,
            expiration_tracking=item.expiration_tracking_enabled,
            operation=operation,
            minimum_quantity=operation.minimum_scan_quantity,
            from_label=from_label,
            to_label=to_label,
            stale_count=hints.stale_count,
            suggested_restock=hints.suggested_restock,
        )


class ExpirationOptionResponse(BaseModel):
    """One date already tracked in the storage this scan touches."""

    expires_on: date
    quantity: int
    suggested: bool
    default_quantity: int

    @classmethod
    def of(cls, option: ExpirationOption) -> "ExpirationOptionResponse":
        return cls(
            expires_on=option.expires_on,
            quantity=option.quantity,
            suggested=option.suggested,
            default_quantity=option.default_quantity,
        )


class ExpirationEntryResponse(BaseModel):
    """The dating step for one scan: how many units need a date, and which dates are on offer."""

    item_name: str
    storage_name: str
    subtitle: str
    target_quantity: int
    requires_exact_total: bool
    allows_new_dates: bool
    allows_other: bool
    max_new_rows: int
    options: list[ExpirationOptionResponse]

    @classmethod
    def of(cls, group: ExpirationEntryGroup) -> "ExpirationEntryResponse":
        return cls(
            item_name=group.item.name,
            storage_name=group.storage.name,
            subtitle=group.spec.card_subtitle,
            target_quantity=group.spec.quantity,
            requires_exact_total=group.spec.requires_exact_total,
            allows_new_dates=group.spec.allows_new_dates,
            allows_other=group.spec.allows_other,
            max_new_rows=group.spec.new_date_row_count,
            options=[ExpirationOptionResponse.of(option) for option in group.options],
        )


class UnknownUpcResponse(BaseModel):
    """What to tell a guest who scanned a barcode no item carries."""

    message: str
