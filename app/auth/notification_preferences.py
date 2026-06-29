"""Central notification preference definitions for admin UI and email scheduling."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum


class NotificationPreferenceGroup(StrEnum):
    ALERT = "alert"
    SUMMARY = "summary"


@dataclass(frozen=True)
class NotificationPreference:
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
    NotificationPreference("alert_for_stockout", "Stockout", NotificationPreferenceGroup.ALERT, True),
    NotificationPreference("alert_for_stockout_pred", "Pred Stockout", NotificationPreferenceGroup.ALERT, True),
    NotificationPreference("alert_for_low", "Low", NotificationPreferenceGroup.ALERT, True),
    NotificationPreference("alert_for_low_pred", "Pred Low", NotificationPreferenceGroup.ALERT, True),
    NotificationPreference("alert_for_stale_count", "Stale Count", NotificationPreferenceGroup.ALERT, True),
    NotificationPreference("alert_for_rare_takeout", "Rare Takeout", NotificationPreferenceGroup.ALERT, False),
    NotificationPreference("alert_for_count", "Count", NotificationPreferenceGroup.ALERT, True),
    NotificationPreference("alert_for_restock", "Restock", NotificationPreferenceGroup.ALERT, True),
    NotificationPreference("alert_for_takeout", "Takeout", NotificationPreferenceGroup.ALERT, False),
    NotificationPreference("alert_for_transfer", "Transfer", NotificationPreferenceGroup.ALERT, False),
    NotificationPreference(
        "daily_summary",
        "Daily",
        NotificationPreferenceGroup.SUMMARY,
        False,
        due_when=lambda now: True,
        bounds=lambda now: _period_bounds(now, days=1),
    ),
    NotificationPreference(
        "weekly_summary",
        "Weekly",
        NotificationPreferenceGroup.SUMMARY,
        True,
        due_when=lambda now: now.weekday() == 0,
        bounds=_prior_week_bounds,
    ),
    NotificationPreference(
        "monthly_summary",
        "Monthly",
        NotificationPreferenceGroup.SUMMARY,
        True,
        due_when=lambda now: now.day == 1,
        bounds=_prior_month_bounds,
    ),
    NotificationPreference(
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


def due_summary_preferences(local_now: datetime) -> tuple[NotificationPreference, ...]:
    return tuple(preference for preference in SUMMARY_NOTIFICATION_PREFERENCES if preference.due_when is not None and preference.due_when(local_now))
