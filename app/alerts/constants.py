"""Alert constants and enums."""

from enum import Enum

ALERT_RESEND_SUPPRESSION_DAYS = 7


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


class AlertAction(str, Enum):
    """Lifecycle state for one generated alert row.

    PENDING: waiting to be included in an email.
    SENT: already emailed.
    SUPPRESSED: intentionally not emailed because a stronger related alert covers it.
    CLEARED: cancelled before email because the condition disappeared.
    RESOLVED: emailed earlier, then the condition disappeared.
    """

    PENDING = "pending"
    SENT = "sent"
    SUPPRESSED = "suppressed"
    CLEARED = "cleared"
    RESOLVED = "resolved"
