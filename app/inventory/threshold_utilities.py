"""
Inventory Threshold Utilities
=============================

Clear, easy-to-understand threshold ranges and CSS class mappings
for inventory levels, order quantities, and timeline indicators.
"""

from typing import Optional, Union

# =============================================================================
# THRESHOLD CONFIGURATION - Easy to modify and understand
# =============================================================================

# Inventory Level Thresholds (based on current stock count)
INVENTORY_NEGATIVE_THRESHOLD = 0  # Less than 0 = negative (critical error)
INVENTORY_ZERO_THRESHOLD = 0     # Exactly 0 = out of stock (warning)
# Above 0 = normal stock levels

# Order Quantity Thresholds (based on units needed to order)
ORDER_CRITICAL_THRESHOLD = 100   # 100+ units = critical priority
ORDER_HIGH_THRESHOLD = 50        # 50-99 units = high priority
ORDER_MEDIUM_THRESHOLD = 20      # 20-49 units = medium priority
ORDER_LOW_THRESHOLD = 10         # 10-19 units = low priority
ORDER_MINIMAL_THRESHOLD = 1      # 1-9 units = minimal priority
# 0 units = no order needed

# Days Until Low Thresholds (timeline urgency)
DAYS_IMMEDIATE_THRESHOLD = 7     # Less than 7 days = immediate action
DAYS_SOON_THRESHOLD = 30         # 7-30 days = action needed soon
DAYS_MODERATE_THRESHOLD = 90     # 31-90 days = moderate planning
# 90+ days = good stock levels

# Maximum display value for days (cap very large numbers)
MAX_DAYS_DISPLAY = 365

# =============================================================================
# CSS CLASS MAPPINGS - Corresponds to inventory-thresholds.css
# =============================================================================

INVENTORY_LEVEL_CLASSES = {
    'negative': 'inventory-level-negative',
    'zero': 'inventory-level-zero',
    'normal': 'inventory-level-normal'
}

ORDER_QUANTITY_CLASSES = {
    'critical': 'order-quantity-critical',
    'high': 'order-quantity-high',
    'medium': 'order-quantity-medium',
    'low': 'order-quantity-low',
    'minimal': 'order-quantity-minimal',
    'none': 'order-quantity-none'
}

DAYS_UNTIL_LOW_CLASSES = {
    'immediate': 'days-until-low-immediate',
    'soon': 'days-until-low-soon',
    'moderate': 'days-until-low-moderate',
    'good': 'days-until-low-good'
}

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_inventory_level_threshold_class(inventory_count: Union[int, float]) -> str:
    """Get CSS class for inventory level visual indicators."""
    if inventory_count < INVENTORY_NEGATIVE_THRESHOLD:
        return INVENTORY_LEVEL_CLASSES['negative']
    elif inventory_count == INVENTORY_ZERO_THRESHOLD:
        return INVENTORY_LEVEL_CLASSES['zero']
    else:
        return INVENTORY_LEVEL_CLASSES['normal']


def get_order_quantity_threshold_class(order_amount: Optional[Union[int, float]]) -> str:
    """Get CSS class for order quantity visual indicators."""
    if order_amount is None or order_amount <= 0:
        return ORDER_QUANTITY_CLASSES['none']
    elif order_amount >= ORDER_CRITICAL_THRESHOLD:
        return ORDER_QUANTITY_CLASSES['critical']
    elif order_amount >= ORDER_HIGH_THRESHOLD:
        return ORDER_QUANTITY_CLASSES['high']
    elif order_amount >= ORDER_MEDIUM_THRESHOLD:
        return ORDER_QUANTITY_CLASSES['medium']
    elif order_amount >= ORDER_LOW_THRESHOLD:
        return ORDER_QUANTITY_CLASSES['low']
    else:
        return ORDER_QUANTITY_CLASSES['minimal']


def get_days_until_low_threshold_class(days_until_low: Optional[Union[int, float]]) -> str:
    """Get CSS class for days until low timeline visual indicators."""
    if days_until_low is None or days_until_low <= 0:
        return ''
    elif days_until_low < DAYS_IMMEDIATE_THRESHOLD:
        return DAYS_UNTIL_LOW_CLASSES['immediate']
    elif days_until_low <= DAYS_SOON_THRESHOLD:
        return DAYS_UNTIL_LOW_CLASSES['soon']
    elif days_until_low <= DAYS_MODERATE_THRESHOLD:
        return DAYS_UNTIL_LOW_CLASSES['moderate']
    else:
        return DAYS_UNTIL_LOW_CLASSES['good']


def format_order_amount_display(order_amount: Optional[Union[int, float]]) -> str:
    """Format order amount for template display."""
    if order_amount is None:
        return 'N/A'
    elif order_amount <= 0:
        return '0'
    else:
        return str(int(order_amount))


def format_days_until_low_display(days_until_low: Optional[Union[int, float]]) -> str:
    """Format days until low for template display."""
    if days_until_low is None:
        return 'N/A'
    elif days_until_low > MAX_DAYS_DISPLAY:
        return str(MAX_DAYS_DISPLAY)
    else:
        return f"{days_until_low:.1f}"