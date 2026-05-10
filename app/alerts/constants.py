"""Alert constants and enums."""

from enum import Enum


class AlertCadence(str, Enum):
    """When an alert is eligible for email delivery."""

    HOURLY = "hourly"
    DAILY = "daily"


class AlertType(str, Enum):
    """Supported inventory alert types."""

    STOCKOUT = "stockout"
    STOCKOUT_PRED = "stockout_pred"
    LOW = "low"
    LOW_PRED = "low_pred"
    STALE_COUNT = "stale_count"
    RARE_TAKEOUT = "rare_takeout"
    COUNT_ACTION = "count_action"
    RESTOCK_ACTION = "restock_action"
    TAKEOUT_ACTION = "takeout_action"
    TRANSFER_ACTION = "transfer_action"

    @property
    def color(self) -> str:
        if self == AlertType.STOCKOUT:
            return "#9F1F1F"
        if self in {
            AlertType.STOCKOUT_PRED,
            AlertType.LOW,
            AlertType.LOW_PRED,
            AlertType.STALE_COUNT,
            AlertType.RARE_TAKEOUT,
        }:
            return "#8A5A00"
        return "#2F6B4F"

    @property
    def cadence(self) -> AlertCadence:
        if self == AlertType.STOCKOUT:
            return AlertCadence.HOURLY
        return AlertCadence.DAILY

    @property
    def allow_early(self) -> bool:
        """Allow this pending alert to ride along when another email is due."""
        return self not in {
            AlertType.COUNT_ACTION,
            AlertType.RESTOCK_ACTION,
            AlertType.TAKEOUT_ACTION,
            AlertType.TRANSFER_ACTION,
        }


class AlertAction(str, Enum):
    """Lifecycle state for one generated alert row."""

    PENDING = "pending"
    SENT = "sent"
    SUPPRESSED = "suppressed"
    CLEARED = "cleared"
