"""Central notification preference definitions for admin UI and email scheduling."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum


class NotificationPreferenceGroup(StrEnum):
    ALERT = "ALERT"
    SUMMARY = "SUMMARY"


class NotificationPreferenceKey(StrEnum):
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
    DAILY_SUMMARY = "DAILY_SUMMARY"
    WEEKLY_SUMMARY = "WEEKLY_SUMMARY"
    MONTHLY_SUMMARY = "MONTHLY_SUMMARY"
    YEARLY_SUMMARY = "YEARLY_SUMMARY"


class AlertEmailFrequency(StrEnum):
    INSTANT = "INSTANT"
    HOURLY = "HOURLY"
    DAILY = "DAILY"

    @property
    def label(self) -> str:
        return ALERT_EMAIL_FREQUENCY_LABELS[self]


ALERT_EMAIL_FREQUENCY_LABELS = {
    AlertEmailFrequency.INSTANT: "Instant (10 min)",
    AlertEmailFrequency.HOURLY: "Hourly",
    AlertEmailFrequency.DAILY: "Daily",
}
ALERT_EMAIL_FREQUENCY_CHOICES = tuple((frequency.value, frequency.label) for frequency in AlertEmailFrequency)


class ScanAlertScope(StrEnum):
    """Which items a recipient's scan-activity alerts (count/restock/takeout/transfer) cover."""

    ALL = "ALL"
    FLAGGED = "FLAGGED"

    @property
    def label(self) -> str:
        return SCAN_ALERT_SCOPE_LABELS[self]


SCAN_ALERT_SCOPE_LABELS = {
    ScanAlertScope.ALL: "All items",
    ScanAlertScope.FLAGGED: "Flagged items only",
}
SCAN_ALERT_SCOPE_CHOICES = tuple((scope.value, scope.label) for scope in ScanAlertScope)


@dataclass(frozen=True)
class NotificationPreference:
    key: NotificationPreferenceKey
    field: str
    label: str
    group: NotificationPreferenceGroup
    default: bool
    due_when: Callable[[datetime], bool] | None = None
    bounds: Callable[[datetime], tuple[datetime, datetime]] | None = None

    @property
    def is_summary(self) -> bool:
        return self.group == NotificationPreferenceGroup.SUMMARY


def _period_bounds(local_now: datetime, *, days: int) -> tuple[datetime, datetime]:
    end_local = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    return _utc_naive(end_local - timedelta(days=days)), _utc_naive(end_local)


def _prior_week_bounds(local_now: datetime) -> tuple[datetime, datetime]:
    end_local = (local_now - timedelta(days=local_now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    return _utc_naive(end_local - timedelta(days=7)), _utc_naive(end_local)


def _prior_month_bounds(local_now: datetime) -> tuple[datetime, datetime]:
    end_local = local_now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    previous_month = (end_local - timedelta(days=1)).replace(day=1)
    return _utc_naive(previous_month), _utc_naive(end_local)


def _prior_year_bounds(local_now: datetime) -> tuple[datetime, datetime]:
    end_local = local_now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    return _utc_naive(end_local.replace(year=end_local.year - 1)), _utc_naive(end_local)


def _utc_naive(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(tzinfo=None)


NOTIFICATION_PREFERENCES = (
    NotificationPreference(NotificationPreferenceKey.STOCKOUT, "alert_for_stockout", "Stockout", NotificationPreferenceGroup.ALERT, True),
    NotificationPreference(
        NotificationPreferenceKey.STOCKOUT_FORECAST,
        "alert_for_stockout_pred",
        "Pred Stockout",
        NotificationPreferenceGroup.ALERT,
        True,
    ),
    NotificationPreference(NotificationPreferenceKey.LOW_STOCK, "alert_for_low", "Low", NotificationPreferenceGroup.ALERT, True),
    NotificationPreference(
        NotificationPreferenceKey.LOW_STOCK_FORECAST,
        "alert_for_low_pred",
        "Pred Low",
        NotificationPreferenceGroup.ALERT,
        True,
    ),
    NotificationPreference(NotificationPreferenceKey.STALE_COUNT, "alert_for_stale_count", "Stale Count", NotificationPreferenceGroup.ALERT, True),
    NotificationPreference(
        NotificationPreferenceKey.RARE_TAKEOUT,
        "alert_for_rare_takeout",
        "Rare Takeout",
        NotificationPreferenceGroup.ALERT,
        False,
    ),
    NotificationPreference(NotificationPreferenceKey.COUNT_ACTION, "alert_for_count", "Count", NotificationPreferenceGroup.ALERT, True),
    NotificationPreference(NotificationPreferenceKey.RESTOCK_ACTION, "alert_for_restock", "Restock", NotificationPreferenceGroup.ALERT, True),
    NotificationPreference(NotificationPreferenceKey.TAKEOUT_ACTION, "alert_for_takeout", "Takeout", NotificationPreferenceGroup.ALERT, False),
    NotificationPreference(NotificationPreferenceKey.TRANSFER_ACTION, "alert_for_transfer", "Transfer", NotificationPreferenceGroup.ALERT, False),
    NotificationPreference(NotificationPreferenceKey.UNKNOWN_UPC, "alert_for_unknown_upc", "Unknown UPC", NotificationPreferenceGroup.ALERT, True),
    NotificationPreference(NotificationPreferenceKey.EXPIRED_STOCK, "alert_for_expired_stock", "Expired", NotificationPreferenceGroup.ALERT, True),
    NotificationPreference(NotificationPreferenceKey.EXPIRING_SOON, "alert_for_expiring_soon", "Expiring", NotificationPreferenceGroup.ALERT, True),
    NotificationPreference(
        NotificationPreferenceKey.EXPIRATION_COUNT_NEEDED,
        "alert_for_expiration_count_needed",
        "Exp Count",
        NotificationPreferenceGroup.ALERT,
        True,
    ),
    NotificationPreference(
        NotificationPreferenceKey.DAILY_SUMMARY,
        "daily_summary",
        "Daily",
        NotificationPreferenceGroup.SUMMARY,
        False,
        due_when=lambda now: True,
        bounds=lambda now: _period_bounds(now, days=1),
    ),
    NotificationPreference(
        NotificationPreferenceKey.WEEKLY_SUMMARY,
        "weekly_summary",
        "Weekly",
        NotificationPreferenceGroup.SUMMARY,
        True,
        due_when=lambda now: now.weekday() == 0,
        bounds=_prior_week_bounds,
    ),
    NotificationPreference(
        NotificationPreferenceKey.MONTHLY_SUMMARY,
        "monthly_summary",
        "Monthly",
        NotificationPreferenceGroup.SUMMARY,
        True,
        due_when=lambda now: now.day == 1,
        bounds=_prior_month_bounds,
    ),
    NotificationPreference(
        NotificationPreferenceKey.YEARLY_SUMMARY,
        "yearly_summary",
        "Yearly",
        NotificationPreferenceGroup.SUMMARY,
        True,
        due_when=lambda now: now.month == 1 and now.day == 1,
        bounds=_prior_year_bounds,
    ),
)

ALERT_NOTIFICATION_FIELDS = tuple(
    (preference.field, preference.label) for preference in NOTIFICATION_PREFERENCES if preference.group == NotificationPreferenceGroup.ALERT
)
SUMMARY_NOTIFICATION_FIELDS = tuple(
    (preference.field, preference.label) for preference in NOTIFICATION_PREFERENCES if preference.group == NotificationPreferenceGroup.SUMMARY
)
NOTIFICATION_FIELDS = tuple(preference.field for preference in NOTIFICATION_PREFERENCES)
SUMMARY_NOTIFICATION_PREFERENCES = tuple(
    preference for preference in NOTIFICATION_PREFERENCES if preference.group == NotificationPreferenceGroup.SUMMARY
)
PREFERENCE_BY_FIELD = {preference.field: preference for preference in NOTIFICATION_PREFERENCES}
PREFERENCE_BY_KEY = {preference.key: preference for preference in NOTIFICATION_PREFERENCES}
DEFAULT_ENABLED_BY_KEY = {preference.key: preference.default for preference in NOTIFICATION_PREFERENCES}


def due_summary_preferences(local_now: datetime) -> tuple[NotificationPreference, ...]:
    return tuple(preference for preference in SUMMARY_NOTIFICATION_PREFERENCES if preference.due_when is not None and preference.due_when(local_now))
