"""Constants and enums for inventory module."""

from enum import IntEnum, StrEnum, unique
from typing import Final


class OperationType(StrEnum):
    """Inventory operation types."""

    COUNT = "COUNT"
    RESTOCK = "RESTOCK"
    TAKEOUT = "TAKEOUT"
    TRANSFER = "TRANSFER"

    @property
    def is_count(self) -> bool:
        return self == OperationType.COUNT

    @property
    def is_restock(self) -> bool:
        return self == OperationType.RESTOCK

    @property
    def is_takeout(self) -> bool:
        return self == OperationType.TAKEOUT

    @property
    def is_transfer(self) -> bool:
        return self == OperationType.TRANSFER

    @property
    def minimum_scan_quantity(self) -> int:
        return 0 if self.is_count else 1


class UnknownUpcStatus(StrEnum):
    PENDING = "PENDING"
    RESOLVED = "RESOLVED"
    IGNORE = "IGNORE"

    @property
    def message(self) -> str:
        return UNKNOWN_UPC_STATUS_MESSAGES[self]


UNKNOWN_UPC_REVIEW_MESSAGE: Final[str] = (
    "UPC not recognized yet. This item may already exist under another barcode. "
    "Try scanning a different UPC for now while an admin reviews this code."
)
UNKNOWN_UPC_IGNORED_MESSAGE: Final[str] = "UPC is invalid. Try a different barcode or search by item name."
UNKNOWN_UPC_INVALID_MESSAGE: Final[str] = "Not a valid 12-digit UPC. Try another barcode or search by item name."
UNKNOWN_UPC_LINKED_MESSAGE: Final[str] = "UPC is already linked to an item. Refresh and try scanning again."
UNKNOWN_UPC_STATUS_MESSAGES: Final[dict[UnknownUpcStatus, str]] = {
    UnknownUpcStatus.PENDING: UNKNOWN_UPC_REVIEW_MESSAGE,
    UnknownUpcStatus.RESOLVED: UNKNOWN_UPC_LINKED_MESSAGE,
    UnknownUpcStatus.IGNORE: UNKNOWN_UPC_IGNORED_MESSAGE,
}


@unique
class VirtualLocation(IntEnum):
    """Sentinel `storage_id` values standing in for a real `Storage.id` in scan routing.

    `@unique` makes it impossible to accidentally reuse a value across members, which
    previously caused RESTOCK and TAKEOUT to silently collide at -1.
    """

    RESTOCK = -1
    COUNT = -2
    TAKEOUT = -3


UPC_GENERATION_PREFIX: Final[str] = "042"
UPC_LENGTH: Final[int] = 12
UPC_PAYLOAD_LENGTH: Final[int] = 11
