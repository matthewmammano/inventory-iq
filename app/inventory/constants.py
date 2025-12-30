"""Shared constants, enums, and configuration for inventory module."""

from enum import Enum


class OperationType(Enum):
    """Inventory operation types."""

    count = "COUNT"
    restock = "RESTOCK"
    takeout = "TAKEOUT"
    transfer = "TRANSFER"


# Virtual Location IDs for scan operations
VIRTUAL_LOCATION_RESTOCK: int = -1
VIRTUAL_LOCATION_COUNT: int = -2
VIRTUAL_LOCATION_TAKEOUT: int = -1


# UPC Generation Constants
UPC_GENERATION_START: str = "500000000000"
"""Starting point for auto-generated UPC codes.

UPCs below this threshold are reserved for manual/imported items.
Generated UPCs start at 500000000000 and increment upward.
"""

# Validation Constants
UPC_LENGTH: int = 12
"""Standard UPC-A barcode length (12 digits with check digit)."""


# Future constants can be added here:
# MAX_BATCH_SIZE: int = 10000
# DEFAULT_EXPIRATION_DAYS: int = 365
