"""Constants and enums for inventory module."""

from enum import Enum
from typing import Final


class OperationType(str, Enum):
    """Inventory operation types."""

    COUNT = "COUNT"
    RESTOCK = "RESTOCK"
    TAKEOUT = "TAKEOUT"
    TRANSFER = "TRANSFER"


VIRTUAL_LOCATION_RESTOCK: Final[int] = -1
VIRTUAL_LOCATION_COUNT: Final[int] = -2
VIRTUAL_LOCATION_TAKEOUT: Final[int] = -1

UPC_GENERATION_PREFIX: Final[str] = "5"
UPC_LENGTH: Final[int] = 12
UPC_PAYLOAD_LENGTH: Final[int] = 11
