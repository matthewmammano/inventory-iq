"""Alert constants, enums, and notification policy values."""

from dataclasses import dataclass
from enum import StrEnum

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
    def email_label(self) -> str:
        return f"{self.emoji} {self.value}"

    @property
    def subject_prefix(self) -> str:
        return f"[{self.value}]"


_META = {
    AlertSeverity.CRITICAL: ("🔴", "#9F1F1F"),
    AlertSeverity.HIGH: ("🟠", "#B45309"),
    AlertSeverity.MEDIUM: ("🟡", "#8A5A00"),
    AlertSeverity.LOW: ("🔵", "#2563EB"),
    AlertSeverity.INFO: ("🟢", "#2F6B4F"),
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


class NotificationEmailStatus(StrEnum):
    """Lifecycle for one rendered recipient email."""

    PENDING = "PENDING"
    SENT = "SENT"
    ERROR = "ERROR"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class AlertDefinition:
    """Central metadata for one alert type."""

    label: str
    severity: AlertSeverity
    preference_field: str | None = None
    stock_rank: int = 0
    immediate: bool = False
    discrete_event: bool = False

    @property
    def color(self) -> str:
        return self.severity.color


ALERT_DEFINITIONS = {
    AlertType.STOCKOUT: AlertDefinition("stockouts", AlertSeverity.CRITICAL, "alert_for_stockout", stock_rank=400),
    AlertType.STOCKOUT_FORECAST: AlertDefinition(
        "predicted stockouts",
        AlertSeverity.HIGH,
        "alert_for_stockout_pred",
        stock_rank=300,
    ),
    AlertType.LOW_STOCK: AlertDefinition("low stock", AlertSeverity.HIGH, "alert_for_low", stock_rank=200),
    AlertType.LOW_STOCK_FORECAST: AlertDefinition(
        "predicted low stock",
        AlertSeverity.MEDIUM,
        "alert_for_low_pred",
        stock_rank=100,
    ),
    AlertType.STALE_COUNT: AlertDefinition("stale counts", AlertSeverity.MEDIUM, "alert_for_stale_count", discrete_event=True),
    AlertType.RARE_TAKEOUT: AlertDefinition("rare takeouts", AlertSeverity.MEDIUM, "alert_for_rare_takeout", discrete_event=True),
    AlertType.UNKNOWN_UPC: AlertDefinition("unknown UPCs", AlertSeverity.MEDIUM, immediate=True, discrete_event=True),
    AlertType.COUNT_ACTION: AlertDefinition("count activity", AlertSeverity.INFO, "alert_for_count", immediate=True, discrete_event=True),
    AlertType.RESTOCK_ACTION: AlertDefinition("restock activity", AlertSeverity.INFO, "alert_for_restock", immediate=True, discrete_event=True),
    AlertType.TAKEOUT_ACTION: AlertDefinition("takeout activity", AlertSeverity.INFO, "alert_for_takeout", immediate=True, discrete_event=True),
    AlertType.TRANSFER_ACTION: AlertDefinition("transfer activity", AlertSeverity.INFO, "alert_for_transfer", immediate=True, discrete_event=True),
}

ACTION_ALERT_TYPES = {
    OperationType.COUNT: AlertType.COUNT_ACTION,
    OperationType.RESTOCK: AlertType.RESTOCK_ACTION,
    OperationType.TAKEOUT: AlertType.TAKEOUT_ACTION,
    OperationType.TRANSFER: AlertType.TRANSFER_ACTION,
}

STOCK_ALERT_RANK = {alert_type: definition.stock_rank for alert_type, definition in ALERT_DEFINITIONS.items() if definition.stock_rank}
PREFERENCE_BY_TYPE = {
    alert_type: definition.preference_field for alert_type, definition in ALERT_DEFINITIONS.items() if definition.preference_field is not None
}
LABEL_BY_TYPE = {alert_type: definition.label for alert_type, definition in ALERT_DEFINITIONS.items()}
IMMEDIATE_EVENT_TYPES = {alert_type for alert_type, definition in ALERT_DEFINITIONS.items() if definition.immediate}
DISCRETE_EVENT_TYPES = {alert_type for alert_type, definition in ALERT_DEFINITIONS.items() if definition.discrete_event}
