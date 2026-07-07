"""Alert constants, enums, and notification policy values."""

from dataclasses import dataclass
from enum import StrEnum

from app.auth.notification_preferences import NotificationPreferenceKey
from app.inventory.constants import OperationType


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


class InventoryAlertEventStatus(StrEnum):
    """Lifecycle for one discrete non-stock alert event."""

    PENDING = "PENDING"
    NO_RECIPIENT = "NO_RECIPIENT"
    QUEUED = "QUEUED"
    NOTIFIED = "NOTIFIED"
    CANCELLED = "CANCELLED"
    ERROR = "ERROR"


class AlertSourceType(StrEnum):
    """Traceable source category for a generated discrete alert event."""

    ACTION_LOG = "ACTION_LOG"
    UNKNOWN_UPC_SCAN = "UNKNOWN_UPC_SCAN"
    STALE_COUNT_AUDIT = "STALE_COUNT_AUDIT"
    RARE_TAKEOUT_AUDIT = "RARE_TAKEOUT_AUDIT"
    EXPIRATION_AUDIT = "EXPIRATION_AUDIT"


class NotificationEmailStatus(StrEnum):
    """Lifecycle for one rendered recipient email."""

    PENDING = "PENDING"
    SENT = "SENT"
    ERROR = "ERROR"
    CANCELLED = "CANCELLED"


class NotificationDeliveryKind(StrEnum):
    """Supported rendered notification email types."""

    ALERT = "ALERT"
    REPORT = "REPORT"


@dataclass(frozen=True)
class AlertDefinition:
    """Central metadata for one alert type."""

    label: str
    severity: AlertSeverity
    preference_key: NotificationPreferenceKey | None = None
    stock_rank: int = 0
    immediate: bool = False
    discrete_event: bool = False

    @property
    def color(self) -> str:
        return self.severity.color


ALERT_DEFINITIONS = {
    AlertType.STOCKOUT: AlertDefinition("stockouts", AlertSeverity.CRITICAL, NotificationPreferenceKey.STOCKOUT, stock_rank=400),
    AlertType.STOCKOUT_FORECAST: AlertDefinition(
        "predicted stockouts",
        AlertSeverity.HIGH,
        NotificationPreferenceKey.STOCKOUT_FORECAST,
        stock_rank=300,
    ),
    AlertType.LOW_STOCK: AlertDefinition("low stock", AlertSeverity.MEDIUM, NotificationPreferenceKey.LOW_STOCK, stock_rank=200),
    AlertType.LOW_STOCK_FORECAST: AlertDefinition(
        "predicted low stock",
        AlertSeverity.LOW,
        NotificationPreferenceKey.LOW_STOCK_FORECAST,
        stock_rank=100,
    ),
    AlertType.STALE_COUNT: AlertDefinition("stale counts", AlertSeverity.LOW, NotificationPreferenceKey.STALE_COUNT, discrete_event=True),
    AlertType.RARE_TAKEOUT: AlertDefinition("rare takeouts", AlertSeverity.LOW, NotificationPreferenceKey.RARE_TAKEOUT, discrete_event=True),
    AlertType.UNKNOWN_UPC: AlertDefinition("unknown UPCs", AlertSeverity.LOW, immediate=True, discrete_event=True),
    AlertType.COUNT_ACTION: AlertDefinition(
        "count activity",
        AlertSeverity.INFO,
        NotificationPreferenceKey.COUNT_ACTION,
        immediate=True,
        discrete_event=True,
    ),
    AlertType.RESTOCK_ACTION: AlertDefinition(
        "restock activity",
        AlertSeverity.INFO,
        NotificationPreferenceKey.RESTOCK_ACTION,
        immediate=True,
        discrete_event=True,
    ),
    AlertType.TAKEOUT_ACTION: AlertDefinition(
        "takeout activity",
        AlertSeverity.INFO,
        NotificationPreferenceKey.TAKEOUT_ACTION,
        immediate=True,
        discrete_event=True,
    ),
    AlertType.TRANSFER_ACTION: AlertDefinition(
        "transfer activity",
        AlertSeverity.INFO,
        NotificationPreferenceKey.TRANSFER_ACTION,
        immediate=True,
        discrete_event=True,
    ),
    AlertType.EXPIRED_STOCK: AlertDefinition("expired stock", AlertSeverity.HIGH, NotificationPreferenceKey.EXPIRED_STOCK, discrete_event=True),
    AlertType.EXPIRING_SOON: AlertDefinition("expiring soon", AlertSeverity.MEDIUM, NotificationPreferenceKey.EXPIRING_SOON, discrete_event=True),
    AlertType.EXPIRATION_COUNT_NEEDED: AlertDefinition(
        "expiration counts needed",
        AlertSeverity.LOW,
        NotificationPreferenceKey.EXPIRATION_COUNT_NEEDED,
        immediate=True,
        discrete_event=True,
    ),
}

ACTION_ALERT_TYPES = {
    OperationType.COUNT: AlertType.COUNT_ACTION,
    OperationType.RESTOCK: AlertType.RESTOCK_ACTION,
    OperationType.TAKEOUT: AlertType.TAKEOUT_ACTION,
    OperationType.TRANSFER: AlertType.TRANSFER_ACTION,
}

STOCK_ALERT_RANK = {alert_type: definition.stock_rank for alert_type, definition in ALERT_DEFINITIONS.items() if definition.stock_rank}
PREFERENCE_BY_TYPE = {
    alert_type: definition.preference_key for alert_type, definition in ALERT_DEFINITIONS.items() if definition.preference_key is not None
}
LABEL_BY_TYPE = {alert_type: definition.label for alert_type, definition in ALERT_DEFINITIONS.items()}
IMMEDIATE_EVENT_TYPES = {alert_type for alert_type, definition in ALERT_DEFINITIONS.items() if definition.immediate}
DISCRETE_EVENT_TYPES = {alert_type for alert_type, definition in ALERT_DEFINITIONS.items() if definition.discrete_event}
