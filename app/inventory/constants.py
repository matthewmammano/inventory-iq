"""Constants and enums for inventory module."""

from enum import Enum
from typing import Final


class OperationType(str, Enum):
    """Inventory operation types."""

    COUNT = "COUNT"
    RESTOCK = "RESTOCK"
    TAKEOUT = "TAKEOUT"
    TRANSFER = "TRANSFER"


class UnknownUpcStatus(str, Enum):
    PENDING = "PENDING"
    RESOLVED = "RESOLVED"
    IGNORE = "IGNORE"


UNKNOWN_UPC_REVIEW_MESSAGE: Final[str] = (
    "UPC not recognized yet. This item may already exist under another barcode. "
    "Try scanning a different UPC for now while an admin reviews this code."
)
UNKNOWN_UPC_IGNORED_MESSAGE: Final[str] = "UPC is invalid. Try a different barcode or search by item name."
UNKNOWN_UPC_INVALID_MESSAGE: Final[str] = "Not a valid 12-digit UPC. Try another barcode or search by item name."
UNKNOWN_UPC_LINKED_MESSAGE: Final[str] = "UPC is already linked to an item. Refresh and try scanning again."


VIRTUAL_LOCATION_RESTOCK: Final[int] = -1
VIRTUAL_LOCATION_COUNT: Final[int] = -2
VIRTUAL_LOCATION_TAKEOUT: Final[int] = -1

UPC_GENERATION_PREFIX: Final[str] = "042"
UPC_LENGTH: Final[int] = 12
UPC_PAYLOAD_LENGTH: Final[int] = 11
