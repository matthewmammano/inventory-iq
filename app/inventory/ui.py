"""CSS class helpers for inventory visuals."""

# Thresholds
_ORD_CRITICAL, _ORD_HIGH, _ORD_MEDIUM, _ORD_LOW = 100, 50, 20, 10
_DAYS_IMMEDIATE, _DAYS_SOON, _DAYS_MODERATE = 30, 90, 180


def get_inventory_level_class(count: int | float) -> str:
    if count < 0:
        return "inventory-level-negative"
    elif count == 0:
        return "inventory-level-zero"
    return "inventory-level-normal"


def get_order_quantity_class(amount: int | float | None) -> str:
    if amount is None or amount <= 0:
        return "order-quantity-none"
    if amount >= _ORD_CRITICAL:
        return "order-quantity-critical"
    if amount >= _ORD_HIGH:
        return "order-quantity-high"
    if amount >= _ORD_MEDIUM:
        return "order-quantity-medium"
    if amount >= _ORD_LOW:
        return "order-quantity-low"
    return "order-quantity-minimal"


def get_days_until_low_class(days: int | float | None) -> str:
    if days is None or days <= 0:
        return ""
    if days < _DAYS_IMMEDIATE:
        return "days-until-low-immediate"
    if days <= _DAYS_SOON:
        return "days-until-low-soon"
    if days <= _DAYS_MODERATE:
        return "days-until-low-moderate"
    return "days-until-low-good"
