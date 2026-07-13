"""Alert constants, enums, and notification policy values."""

from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum

from app.auth.notification_preferences import NotificationPreferenceKey
from app.inventory.constants import OperationType

ALERT_RESEND_COOLDOWN = timedelta(days=7)


class AlertType(StrEnum):
    """Supported stock-state and discrete inventory alert types."""

    STOCKOUT = "STOCKOUT"
    STOCKOUT_FORECAST = "STOCKOUT_FORECAST"
    LOW_STOCK = "LOW_STOCK"
    LOW_STOCK_FORECAST = "LOW_STOCK_FORECAST"
    STALE_COUNT = "STALE_COUNT"
    RARE_TAKEOUT = "RARE_TAKEOUT"
    COUNT_ACTION = "COUNT_ACTION"
    RESTOCK_ACTION = "RESTOCK_ACTION"
    TAKEOUT_ACTION = "TAKEOUT_ACTION"
    TRANSFER_ACTION = "TRANSFER_ACTION"
    UNKNOWN_UPC = "UNKNOWN_UPC"
    EXPIRED_STOCK = "EXPIRED_STOCK"
    EXPIRING_SOON = "EXPIRING_SOON"
    EXPIRATION_COUNT_NEEDED = "EXPIRATION_COUNT_NEEDED"

    @property
    def color(self) -> str:
        return ALERT_DEFINITIONS[self].color

    @property
    def severity(self) -> "AlertSeverity":
        return ALERT_DEFINITIONS[self].severity


class AlertSeverity(StrEnum):
    """Stable severity names stored by the ORM and used by application logic."""

    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"

    @property
    def emoji(self) -> str:
        return _META[self][0]

    @property
    def color(self) -> str:
        return _META[self][1]

    @property
    def subject_prefix(self) -> str:
        return f"{self.emoji} [{self.value}]"


_META = {
    AlertSeverity.CRITICAL: ("🟥", "#9F1F1F"),
    AlertSeverity.HIGH: ("🟧", "#C05E14"),
    AlertSeverity.MEDIUM: ("🟨", "#AA9B13"),
    AlertSeverity.LOW: ("🟩", "#0A813C"),
    AlertSeverity.INFO: ("🟦", "#2563EB"),
}


SEVERITY_ORDER = (
    AlertSeverity.CRITICAL,
    AlertSeverity.HIGH,
    AlertSeverity.MEDIUM,
    AlertSeverity.LOW,
    AlertSeverity.INFO,
)


class AlertStatus(StrEnum):
    """Whether an alert's underlying problem is still live.

    Per-recipient notification history lives in `alert_notifications`, never here.
    """

    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ClosedReason(StrEnum):
    """Why an open alert was closed."""

    RESOLVED = "RESOLVED"  # the real condition went away: recount, restock, UPC assigned, admin dismissal
    SUPERSEDED = "SUPERSEDED"  # a different-type alert for the same subject replaced it (low stock -> stockout)
    SENT = "SENT"  # informational alert with nothing to resolve; closed once communicated


class DeliveryStatus(StrEnum):
    """Terminal outcome of one notification email send attempt (write-once audit)."""

    SENT = "SENT"
    ERROR = "ERROR"


class NotificationDeliveryKind(StrEnum):
    """Supported rendered notification email types."""

    ALERT = "ALERT"
    REPORT = "REPORT"


@dataclass(frozen=True)
class AlertDefinition:
    """Central metadata for one alert type.

    `resend_after` is how long an unaddressed alert waits before a recipient is
    re-notified while it stays open; `None` means notify once and never again.
    """

    label: str
    severity: AlertSeverity
    preference_key: NotificationPreferenceKey | None = None
    stock_rank: int = 0
    discrete_event: bool = False
    resend_after: timedelta | None = None
    countable: bool = True  # pluralize `label` with the summary tile count; False for uncountable phrases

    @property
    def color(self) -> str:
        return self.severity.color


ALERT_DEFINITIONS = {
    AlertType.STOCKOUT: AlertDefinition(
        "stockout", AlertSeverity.CRITICAL, NotificationPreferenceKey.STOCKOUT, stock_rank=400, resend_after=ALERT_RESEND_COOLDOWN
    ),
    AlertType.STOCKOUT_FORECAST: AlertDefinition(
        "predicted stockout",
        AlertSeverity.HIGH,
        NotificationPreferenceKey.STOCKOUT_FORECAST,
        stock_rank=300,
        resend_after=ALERT_RESEND_COOLDOWN,
    ),
    AlertType.LOW_STOCK: AlertDefinition(
        "low stock", AlertSeverity.MEDIUM, NotificationPreferenceKey.LOW_STOCK, stock_rank=200, resend_after=ALERT_RESEND_COOLDOWN, countable=False
    ),
    AlertType.LOW_STOCK_FORECAST: AlertDefinition(
        "predicted low stock",
        AlertSeverity.LOW,
        NotificationPreferenceKey.LOW_STOCK_FORECAST,
        stock_rank=100,
        resend_after=ALERT_RESEND_COOLDOWN,
        countable=False,
    ),
    AlertType.STALE_COUNT: AlertDefinition(
        "stale count", AlertSeverity.LOW, NotificationPreferenceKey.STALE_COUNT, discrete_event=True, resend_after=ALERT_RESEND_COOLDOWN
    ),
    AlertType.RARE_TAKEOUT: AlertDefinition("rare takeout", AlertSeverity.LOW, NotificationPreferenceKey.RARE_TAKEOUT, discrete_event=True),
    AlertType.UNKNOWN_UPC: AlertDefinition(
        "unknown UPC", AlertSeverity.LOW, NotificationPreferenceKey.UNKNOWN_UPC, discrete_event=True, resend_after=ALERT_RESEND_COOLDOWN
    ),
    AlertType.COUNT_ACTION: AlertDefinition(
        "count activity", AlertSeverity.INFO, NotificationPreferenceKey.COUNT_ACTION, discrete_event=True, countable=False
    ),
    AlertType.RESTOCK_ACTION: AlertDefinition(
        "restock activity", AlertSeverity.INFO, NotificationPreferenceKey.RESTOCK_ACTION, discrete_event=True, countable=False
    ),
    AlertType.TAKEOUT_ACTION: AlertDefinition(
        "takeout activity", AlertSeverity.INFO, NotificationPreferenceKey.TAKEOUT_ACTION, discrete_event=True, countable=False
    ),
    AlertType.TRANSFER_ACTION: AlertDefinition(
        "transfer activity", AlertSeverity.INFO, NotificationPreferenceKey.TRANSFER_ACTION, discrete_event=True, countable=False
    ),
    AlertType.EXPIRED_STOCK: AlertDefinition(
        "expired stock",
        AlertSeverity.HIGH,
        NotificationPreferenceKey.EXPIRED_STOCK,
        discrete_event=True,
        resend_after=ALERT_RESEND_COOLDOWN,
        countable=False,
    ),
    AlertType.EXPIRING_SOON: AlertDefinition(
        "expiring soon",
        AlertSeverity.MEDIUM,
        NotificationPreferenceKey.EXPIRING_SOON,
        discrete_event=True,
        resend_after=ALERT_RESEND_COOLDOWN,
        countable=False,
    ),
    AlertType.EXPIRATION_COUNT_NEEDED: AlertDefinition(
        "expiration count needed",
        AlertSeverity.LOW,
        NotificationPreferenceKey.EXPIRATION_COUNT_NEEDED,
        discrete_event=True,
        resend_after=ALERT_RESEND_COOLDOWN,
    ),
}

ACTION_ALERT_TYPES = {
    OperationType.COUNT: AlertType.COUNT_ACTION,
    OperationType.RESTOCK: AlertType.RESTOCK_ACTION,
    OperationType.TAKEOUT: AlertType.TAKEOUT_ACTION,
    OperationType.TRANSFER: AlertType.TRANSFER_ACTION,
}

STOCK_ALERT_RANK = {alert_type: definition.stock_rank for alert_type, definition in ALERT_DEFINITIONS.items() if definition.stock_rank}
STOCK_ALERT_TYPES = frozenset(STOCK_ALERT_RANK)
PREFERENCE_BY_TYPE = {
    alert_type: definition.preference_key for alert_type, definition in ALERT_DEFINITIONS.items() if definition.preference_key is not None
}
# Canonical display priority (stockout -> forecast -> low -> ... -> expiration), used to order email summary tiles.
ALERT_TYPE_ORDER = {alert_type: index for index, alert_type in enumerate(ALERT_DEFINITIONS)}
DISCRETE_EVENT_TYPES = {alert_type for alert_type, definition in ALERT_DEFINITIONS.items() if definition.discrete_event}
RESEND_AFTER_BY_TYPE = {alert_type: definition.resend_after for alert_type, definition in ALERT_DEFINITIONS.items()}
