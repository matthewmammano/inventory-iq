"""
Inventory module configuration constants.

Centralizes magic numbers, thresholds, and configuration values
for inventory management functionality.
"""


class InventoryConfig:
    """Configuration constants for inventory operations."""

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
