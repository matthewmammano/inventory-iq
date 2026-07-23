"""SQLAlchemy ORM models for auth domain."""

import string
from datetime import UTC, datetime

from flask_login import UserMixin
from sqlalchemy import JSON, Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.ext.mutable import MutableList
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates
from werkzeug.security import check_password_hash, generate_password_hash

from app.shared.clock import utc_now_naive
from app.shared.database import Base
from app.shared.validators import (
    normalize_hex_color,
    validate_email_format,
    validate_hhmm_time,
    validate_image_url,
    validate_password_strength,
    validate_pin,
    validate_positive_integer,
    validate_string_length,
    validate_timezone,
)

from .constants import BLACK_HEX, WHITE_HEX
from .location_filters import normalize_location_filter_ids
from .notification_preferences import DEFAULT_ENABLED_BY_KEY, PREFERENCE_BY_FIELD, AlertEmailFrequency, NotificationPreferenceKey, ScanAlertScope


class Agency(Base, UserMixin):
    """Primary agency model (referenced as 'agency' in code)."""

    __tablename__ = "agencies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    display_name: Mapped[str] = mapped_column(String(50), unique=True)
    email: Mapped[str] = mapped_column(String(128), unique=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    image: Mapped[str | None] = mapped_column(Text)
    timezone: Mapped[str] = mapped_column(String(50), default="America/New_York")
    password: Mapped[str | None] = mapped_column(Text)
    pin: Mapped[str] = mapped_column(Text)
    user_count_allow: Mapped[bool] = mapped_column(Boolean, default=False)
    user_restock_allow: Mapped[bool] = mapped_column(Boolean, default=False)

    # Alert detection thresholds
    lead_time_days: Mapped[int] = mapped_column(Integer, default=21)
    count_last_days: Mapped[int] = mapped_column(Integer, default=90)
    alert_rare_scan_days: Mapped[int] = mapped_column(Integer, default=90)
    expiration_notice_days: Mapped[int] = mapped_column(Integer, default=30)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))

    items = relationship("Item", backref="agency", lazy="select")
    logs = relationship("ActionLog", backref="agency", lazy="select")
    password_reset_pins = relationship("PasswordResetPins", back_populates="agency", lazy="select")
    item_tags = relationship("ItemTag", backref="agency", lazy="select")
    locations = relationship("Location", back_populates="agency", lazy="select")
    storages = relationship("Storage", back_populates="agency", lazy="select")

    def set_password(self, password: str) -> None:
        """Set the password hash."""
        validate_password_strength(password)
        self.password = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        """Check the password hash."""
        if not self.password:
            return False
        return check_password_hash(self.password, password)

    def set_pin(self, pin: str) -> None:
        """Set the admin PIN hash."""
        validate_pin(pin)
        self.pin = generate_password_hash(pin)

    def check_pin(self, pin: str) -> bool:
        """Check the admin PIN hash."""
        return check_password_hash(self.pin, pin)

    @property
    def agency_context(self) -> dict[str, str | int | None]:
        """Context dict for Flask-Login."""
        return {
            "agency_id": self.id,
            "display_name": self.display_name,
            "image": self.image,
            "timezone": self.timezone,
        }

    @validates("display_name")
    def validate_display_name(self, _key: str, value: str) -> str | None:
        return validate_string_length(value, "display_name", 50, allow_none=False, allow_empty=False)

    @validates("email")
    def validate_email(self, _key: str, value: str | None) -> str | None:
        return validate_email_format(value, max_length=128, allow_none=False)

    @validates("image")
    def validate_image(self, _key: str, value: str | None) -> str | None:
        return validate_image_url(value)

    @validates("timezone")
    def validate_timezone_field(self, _key: str, value: str) -> str:
        return validate_timezone(value)

    @validates("lead_time_days", "alert_rare_scan_days", "count_last_days", "expiration_notice_days")
    def validate_positive_day_setting(self, key: str, value: int | None) -> int:
        validated = validate_positive_integer(value, key, allow_none=False)
        if validated is None:
            raise ValueError(f"{key} cannot be None")
        return validated


class PasswordResetPins(Base):
    """Hashed short-lived password reset PIN for kiosk-friendly reset flow."""

    __tablename__ = "password_reset_pins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agency_id: Mapped[int] = mapped_column(Integer, ForeignKey("agencies.id"), index=True)
    pin_hash: Mapped[str] = mapped_column(String(255))
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)

    agency = relationship("Agency", back_populates="password_reset_pins", lazy="select")

    def set_pin(self, pin: str) -> None:
        self.pin_hash = generate_password_hash(pin)

    def check_pin(self, pin: str) -> bool:
        return check_password_hash(self.pin_hash, pin)


class NotificationRecipient(Base):
    """Additional emails per agency."""

    __tablename__ = "notification_recipients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agency_id: Mapped[int] = mapped_column(Integer, ForeignKey("agencies.id"), index=True)
    email: Mapped[str] = mapped_column(String(128))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    location_filter_ids: Mapped[list[int] | None] = mapped_column(MutableList.as_mutable(JSON), nullable=True)
    quiet_start_time: Mapped[str | None] = mapped_column(String(5), nullable=True)
    quiet_end_time: Mapped[str | None] = mapped_column(String(5), nullable=True)
    alert_frequency: Mapped[AlertEmailFrequency] = mapped_column(
        SAEnum(AlertEmailFrequency, native_enum=False, length=16),
        default=AlertEmailFrequency.HOURLY,
    )
    scan_alert_scope: Mapped[ScanAlertScope] = mapped_column(
        SAEnum(ScanAlertScope, native_enum=False, length=16),
        default=ScanAlertScope.ALL,
    )

    preferences = relationship(
        "NotificationPreferenceSetting",
        back_populates="recipient",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        UniqueConstraint("agency_id", "email", name="uq_notification_recipients_agency_email"),
        CheckConstraint(
            "(quiet_start_time IS NULL AND quiet_end_time IS NULL) OR (quiet_start_time IS NOT NULL AND quiet_end_time IS NOT NULL)",
            name="ck_notification_recipients_quiet_hours_pair",
        ),
    )

    @validates("email")
    def validate_email(self, _key: str, value: str | None) -> str | None:
        return validate_email_format(value, max_length=128, allow_none=False)

    @validates("location_filter_ids")
    def validate_location_filter_ids(self, _key: str, value: list[int] | None) -> list[int] | None:
        return normalize_location_filter_ids(value)

    @validates("quiet_start_time", "quiet_end_time")
    def validate_quiet_time(self, key: str, value: str | None) -> str | None:
        return validate_hhmm_time(value, key)

    @property
    def quiet_hours_label(self) -> str:
        if self.quiet_start_time and self.quiet_end_time:
            return f"{self.quiet_start_time}-{self.quiet_end_time}"
        return "None"

    def preference_enabled(self, field_or_key: str | NotificationPreferenceKey) -> bool:
        key = _preference_key(field_or_key)
        row = next((preference for preference in self.preferences if preference.preference_key == key), None)
        return bool(row.enabled) if row else DEFAULT_ENABLED_BY_KEY[key]


class NotificationPreferenceSetting(Base):
    """One recipient-level notification preference toggle."""

    __tablename__ = "notification_preferences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recipient_id: Mapped[int] = mapped_column(Integer, ForeignKey("notification_recipients.id", ondelete="CASCADE"), index=True)
    preference_key: Mapped[NotificationPreferenceKey] = mapped_column(
        SAEnum(NotificationPreferenceKey, native_enum=False, length=32),
        index=True,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    recipient = relationship("NotificationRecipient", back_populates="preferences", lazy="selectin")

    __table_args__ = (UniqueConstraint("recipient_id", "preference_key", name="uq_notification_preferences_recipient_key"),)


def _preference_key(field_or_key: str | NotificationPreferenceKey) -> NotificationPreferenceKey:
    if isinstance(field_or_key, NotificationPreferenceKey):
        return field_or_key
    preference = PREFERENCE_BY_FIELD.get(field_or_key)
    if preference is None:
        return NotificationPreferenceKey(field_or_key)
    return preference.key


class Location(Base):
    """Top-level physical locations per agency."""

    __tablename__ = "agency_locations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agency_id: Mapped[int] = mapped_column(Integer, ForeignKey("agencies.id"), index=True)
    name: Mapped[str] = mapped_column(String(50))

    agency = relationship("Agency", back_populates="locations", lazy="select")
    storages = relationship(
        "Storage",
        back_populates="location",
        lazy="selectin",
        order_by="Storage.name",
    )

    __table_args__ = (UniqueConstraint("agency_id", "name", name="uq_agency_locations_agency_name"),)

    @validates("name")
    def validate_name(self, _key: str, value: str) -> str | None:
        return validate_string_length(value, "name", 50, allow_none=False, allow_empty=False)


class AgencyDevice(Base):
    """Browser/device default location for one agency."""

    __tablename__ = "agency_devices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agency_id: Mapped[int] = mapped_column(Integer, ForeignKey("agencies.id"), index=True)
    agency_location_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("agency_locations.id"), nullable=True)
    device_token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))

    location = relationship("Location", lazy="select")


class Storage(Base):
    """Storage units within a location."""

    __tablename__ = "agency_storages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agency_id: Mapped[int] = mapped_column(Integer, ForeignKey("agencies.id"), index=True)
    location_id: Mapped[int] = mapped_column(Integer, ForeignKey("agency_locations.id"), index=True)
    name: Mapped[str] = mapped_column(String(50))
    user_access_from: Mapped[bool] = mapped_column(Boolean, default=True)
    user_access_to: Mapped[bool] = mapped_column(Boolean, default=True)

    agency = relationship("Agency", back_populates="storages", lazy="select")
    location = relationship("Location", back_populates="storages", lazy="select")

    __table_args__ = (UniqueConstraint("location_id", "name", name="uq_agency_storages_location_name"),)

    @validates("name")
    def validate_name(self, _key: str, value: str) -> str | None:
        return validate_string_length(value, "name", 50, allow_none=False, allow_empty=False)

    @property
    def full_name(self) -> str:
        """User-facing location/storage label."""
        location_name = self.location.name if self.location else ""
        return f"{location_name} / {self.name}" if location_name else self.name

    @property
    def history_name(self) -> str:
        """Compact label for movement history."""
        location_name = self.location.name if self.location else ""
        return f"{location_name} - {self.name}" if location_name else self.name


class ItemTag(Base):
    """Agency-defined item tags."""

    __tablename__ = "agency_item_tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agency_id: Mapped[int] = mapped_column(Integer, ForeignKey("agencies.id"), index=True)
    tag_name: Mapped[str] = mapped_column(String(50))
    color: Mapped[str] = mapped_column(String(7))
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    __table_args__ = (UniqueConstraint("agency_id", "tag_name", name="uq_agency_item_tags_agency_tag"),)

    @property
    def text_color(self) -> str:
        """Calculate contrasting text color."""
        color = (self.color or "").lstrip("#")
        if len(color) != 6 or any(c not in string.hexdigits for c in color):
            return BLACK_HEX
        r, g, b = int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)
        brightness = r * 0.299 + g * 0.587 + b * 0.114
        return WHITE_HEX if brightness < 128 else BLACK_HEX

    @validates("tag_name")
    def validate_tag_name(self, _key: str, value: str) -> str | None:
        return validate_string_length(value, "tag_name", 50, allow_none=False, allow_empty=False)

    @validates("color")
    def validate_color(self, _key: str, value: str | None) -> str:
        return normalize_hex_color(value)
