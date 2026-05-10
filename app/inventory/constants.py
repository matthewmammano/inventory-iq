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

UPC_GENERATION_START: Final[str] = "500000000000"
UPC_LENGTH: Final[int] = 12
