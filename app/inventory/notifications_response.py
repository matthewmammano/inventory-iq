"""Response models for the notification recipients admin screen."""

from collections.abc import Mapping, Sequence
from typing import Final, Self

from pydantic import BaseModel

from app.auth.models import NotificationRecipient
from app.auth.notification_preferences import (
    NOTIFICATION_PREFERENCES,
    AlertEmailFrequency,
    NotificationPreference,
    NotificationPreferenceGroup,
    ScanAlertScope,
)

ALL_LOCATIONS_LABEL: Final[str] = "All locations"
PREVIEW_SEPARATOR: Final[str] = " - "
GROUP_PREVIEW_WORDS: Final[dict[NotificationPreferenceGroup, tuple[str, str]]] = {
    NotificationPreferenceGroup.ALERT: ("alert", "alerts"),
    NotificationPreferenceGroup.SUMMARY: ("summary", "summaries"),
}


class NotificationToggleResponse(BaseModel):
    """One toggle's field name, label, and group, so the client labels a row without a table of its own."""

    field: str
    label: str
    group: NotificationPreferenceGroup

    @classmethod
    def of(cls, preference: NotificationPreference) -> Self:
        return cls(field=preference.field, label=preference.label, group=preference.group)


NOTIFICATION_TOGGLES: Final[tuple[NotificationToggleResponse, ...]] = tuple(
    NotificationToggleResponse.of(preference) for preference in NOTIFICATION_PREFERENCES
)


def _enabled_summary(toggles: Mapping[str, bool], group: NotificationPreferenceGroup) -> str:
    count = sum(1 for preference in NOTIFICATION_PREFERENCES if preference.group == group and toggles[preference.field])
    singular, plural = GROUP_PREVIEW_WORDS[group]
    return f"{count} {singular if count == 1 else plural}"


def _preview(recipient: NotificationRecipient, location_names: Sequence[str], toggles: Mapping[str, bool]) -> str:
    """One line standing in for the recipient's 23 columns until its modal is opened."""
    parts = [
        recipient.email,
        ", ".join(location_names) or ALL_LOCATIONS_LABEL,
        recipient.alert_frequency.label,
        _enabled_summary(toggles, NotificationPreferenceGroup.ALERT),
        _enabled_summary(toggles, NotificationPreferenceGroup.SUMMARY),
    ]
    if recipient.quiet_start_time and recipient.quiet_end_time:
        parts.append(f"quiet {recipient.quiet_hours_label}")
    return PREVIEW_SEPARATOR.join(parts)


class NotificationRecipientResponse(BaseModel):
    """One recipient as its row preview plus every field the edit modal writes back."""

    id: int
    email: str
    location_filter_ids: list[int]
    location_names: list[str]
    quiet_start_time: str | None
    quiet_end_time: str | None
    quiet_hours_label: str
    alert_frequency: AlertEmailFrequency
    alert_frequency_label: str
    scan_alert_scope: ScanAlertScope
    scan_alert_scope_label: str
    toggles: dict[str, bool]
    preview: str

    @classmethod
    def of(cls, recipient: NotificationRecipient, location_names: Mapping[int, str]) -> Self:
        toggles = {preference.field: recipient.preference_enabled(preference.field) for preference in NOTIFICATION_PREFERENCES}
        watched_ids = list(recipient.location_filter_ids or [])
        watched_names = [location_names[location_id] for location_id in watched_ids if location_id in location_names]
        return cls(
            id=recipient.id,
            email=recipient.email,
            location_filter_ids=watched_ids,
            location_names=watched_names,
            quiet_start_time=recipient.quiet_start_time,
            quiet_end_time=recipient.quiet_end_time,
            quiet_hours_label=recipient.quiet_hours_label,
            alert_frequency=recipient.alert_frequency,
            alert_frequency_label=recipient.alert_frequency.label,
            scan_alert_scope=recipient.scan_alert_scope,
            scan_alert_scope_label=recipient.scan_alert_scope.label,
            toggles=toggles,
            preview=_preview(recipient, watched_names, toggles),
        )


class NotificationRecipientListResponse(BaseModel):
    """Every active recipient, with the toggle table its previews and modal columns are drawn from."""

    toggle_fields: list[NotificationToggleResponse]
    recipients: list[NotificationRecipientResponse]

    @classmethod
    def of(cls, recipients: Sequence[NotificationRecipient], location_names: Mapping[int, str]) -> Self:
        return cls(
            toggle_fields=list(NOTIFICATION_TOGGLES),
            recipients=[NotificationRecipientResponse.of(recipient, location_names) for recipient in recipients],
        )
