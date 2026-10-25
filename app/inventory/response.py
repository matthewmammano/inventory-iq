"""Response models for the scan surface: items, storage choices, and a saved scan."""

from pydantic import BaseModel, ConfigDict, RootModel

from app.auth.models import Storage
from app.auth.response import StorageResponse

from .constants import OperationType
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
    upc: str
    upcs: list[str]
    last_accessed: str
    tags: list[ItemTagResponse]

    @classmethod
    def of(cls, payload: ItemSearchPayload) -> "ItemResponse":
        return cls(
            id=payload["id"],
            name=payload["name"],
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
