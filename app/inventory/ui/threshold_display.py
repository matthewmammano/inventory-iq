"""Threshold helpers for inventory visuals.

Maps numeric values to CSS classes for inventory levels, order quantities,
and days-until-low indicators. Keep this small and declarative so thresholds
are easy to tweak.
"""

# Threshold configuration (adjust here only)
INVENTORY_NEGATIVE_THRESHOLD = 0
INVENTORY_ZERO_THRESHOLD = 0

ORDER_CRITICAL_THRESHOLD = 100
ORDER_HIGH_THRESHOLD = 50
ORDER_MEDIUM_THRESHOLD = 20
ORDER_LOW_THRESHOLD = 10
ORDER_MINIMAL_THRESHOLD = 1

DAYS_IMMEDIATE_THRESHOLD = 30
DAYS_SOON_THRESHOLD = 30 * 3
DAYS_MODERATE_THRESHOLD = 30 * 6

MAX_DAYS_DISPLAY = 365

INVENTORY_LEVEL_CLASSES = {
    "negative": "inventory-level-negative",
    "zero": "inventory-level-zero",
    "normal": "inventory-level-normal",
}

ORDER_QUANTITY_CLASSES = {
    "critical": "order-quantity-critical",
    "high": "order-quantity-high",
    "medium": "order-quantity-medium",
    "low": "order-quantity-low",
    "minimal": "order-quantity-minimal",
    "none": "order-quantity-none",
}

DAYS_UNTIL_LOW_CLASSES = {
    "immediate": "days-until-low-immediate",
    "soon": "days-until-low-soon",
    "moderate": "days-until-low-moderate",
    "good": "days-until-low-good",
}


def _select_class(
    value: int | float | None, checks: list[tuple[callable, str]], default: str = ""
) -> str:
    """Return the class for the first matching condition, otherwise default."""
    for condition, class_name in checks:
        if condition(value):
            return class_name
    return default


def get_inventory_level_threshold_class(inventory_count: int | float) -> str:
    """CSS class for inventory level."""
    return _select_class(
        inventory_count,
        [
            (
                lambda v: v < INVENTORY_NEGATIVE_THRESHOLD,
                INVENTORY_LEVEL_CLASSES["negative"],
            ),
            (lambda v: v == INVENTORY_ZERO_THRESHOLD, INVENTORY_LEVEL_CLASSES["zero"]),
        ],
        INVENTORY_LEVEL_CLASSES["normal"],
    )


def get_order_quantity_threshold_class(order_amount: int | float | None) -> str:
    """CSS class for order quantity."""
    return _select_class(
        order_amount,
        [
            (lambda v: v is None or v <= 0, ORDER_QUANTITY_CLASSES["none"]),
            (
                lambda v: v >= ORDER_CRITICAL_THRESHOLD,
                ORDER_QUANTITY_CLASSES["critical"],
            ),
            (lambda v: v >= ORDER_HIGH_THRESHOLD, ORDER_QUANTITY_CLASSES["high"]),
            (lambda v: v >= ORDER_MEDIUM_THRESHOLD, ORDER_QUANTITY_CLASSES["medium"]),
            (lambda v: v >= ORDER_LOW_THRESHOLD, ORDER_QUANTITY_CLASSES["low"]),
        ],
        ORDER_QUANTITY_CLASSES["minimal"],
    )


def get_days_until_low_threshold_class(days_until_low: int | float | None) -> str:
    """CSS class for timeline urgency."""
    return _select_class(
        days_until_low,
        [
            (lambda v: v is None or v <= 0, ""),
            (
                lambda v: v < DAYS_IMMEDIATE_THRESHOLD,
                DAYS_UNTIL_LOW_CLASSES["immediate"],
            ),
            (lambda v: v <= DAYS_SOON_THRESHOLD, DAYS_UNTIL_LOW_CLASSES["soon"]),
            (
                lambda v: v <= DAYS_MODERATE_THRESHOLD,
                DAYS_UNTIL_LOW_CLASSES["moderate"],
            ),
        ],
        DAYS_UNTIL_LOW_CLASSES["good"],
    )


def format_order_amount_display(order_amount: int | float | None) -> str:
    """Format order amount for template display."""
    if order_amount is None:
        return "N/A"
    elif order_amount <= 0:
        return "0"
    else:
        return str(int(order_amount))


def format_days_until_low_display(days_until_low: int | float | None) -> str:
    """Format days until low for template display."""
    if days_until_low is None:
        return "N/A"
    elif days_until_low > MAX_DAYS_DISPLAY:
        return str(MAX_DAYS_DISPLAY)
    else:
        return f"{days_until_low:.1f}"
