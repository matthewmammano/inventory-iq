"""SQLAlchemy ORM models for auth domain."""

import string
from datetime import UTC, datetime

from flask_login import UserMixin
from sqlalchemy import JSON, Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
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


class Agencies(Base, UserMixin):
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

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))

    items = relationship("Items", backref="agency", lazy="select")
    logs = relationship("ActionLogs", backref="agency", lazy="select")
    emails = relationship("AgencyEmails", backref="agency", lazy="select")
    password_reset_pins = relationship("PasswordResetPins", back_populates="agency", lazy="select")
    item_tags = relationship("AgencyItemTags", backref="agency", lazy="select")
    locations = relationship("AgencyLocations", back_populates="agency", lazy="select")
    storages = relationship("AgencyStorages", back_populates="agency", lazy="select")

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

    @validates("lead_time_days", "alert_rare_scan_days", "count_last_days")
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

    agency = relationship("Agencies", back_populates="password_reset_pins", lazy="select")

    def set_pin(self, pin: str) -> None:
        self.pin_hash = generate_password_hash(pin)

    def check_pin(self, pin: str) -> bool:
        return check_password_hash(self.pin_hash, pin)


class AgencyEmails(Base):
    """Additional emails per agency."""

    __tablename__ = "agency_emails"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agency_id: Mapped[int] = mapped_column(Integer, ForeignKey("agencies.id"), index=True)
    email: Mapped[str] = mapped_column(String(128), unique=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    location_filter_ids: Mapped[list[int] | None] = mapped_column(MutableList.as_mutable(JSON), nullable=True)
    quiet_start_time: Mapped[str | None] = mapped_column(String(5), nullable=True)
    quiet_end_time: Mapped[str | None] = mapped_column(String(5), nullable=True)

    alert_for_stockout: Mapped[bool] = mapped_column(Boolean, default=True)
    alert_for_stockout_pred: Mapped[bool] = mapped_column(Boolean, default=True)
    alert_for_low: Mapped[bool] = mapped_column(Boolean, default=True)
    alert_for_low_pred: Mapped[bool] = mapped_column(Boolean, default=True)
    alert_for_stale_count: Mapped[bool] = mapped_column(Boolean, default=True)
    alert_for_rare_takeout: Mapped[bool] = mapped_column(Boolean, default=False)
    alert_for_count: Mapped[bool] = mapped_column(Boolean, default=True)
    alert_for_restock: Mapped[bool] = mapped_column(Boolean, default=True)
    alert_for_takeout: Mapped[bool] = mapped_column(Boolean, default=False)
    alert_for_transfer: Mapped[bool] = mapped_column(Boolean, default=False)

    daily_summary: Mapped[bool] = mapped_column(Boolean, default=False)
    weekly_summary: Mapped[bool] = mapped_column(Boolean, default=True)
    monthly_summary: Mapped[bool] = mapped_column(Boolean, default=True)
    yearly_summary: Mapped[bool] = mapped_column(Boolean, default=True)

    __table_args__ = (
        CheckConstraint(
            "(quiet_start_time IS NULL AND quiet_end_time IS NULL) OR (quiet_start_time IS NOT NULL AND quiet_end_time IS NOT NULL)",
            name="ck_agency_emails_quiet_hours_pair",
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


class AgencyLocations(Base):
    """Top-level physical locations per agency."""

    __tablename__ = "agency_locations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agency_id: Mapped[int] = mapped_column(Integer, ForeignKey("agencies.id"), index=True)
    name: Mapped[str] = mapped_column(String(50))

    agency = relationship("Agencies", back_populates="locations", lazy="select")
    storages = relationship(
        "AgencyStorages",
        back_populates="location",
        lazy="selectin",
        order_by="AgencyStorages.name",
    )

    __table_args__ = (UniqueConstraint("agency_id", "name", name="uq_agency_locations_agency_name"),)

    @validates("name")
    def validate_name(self, _key: str, value: str) -> str | None:
        return validate_string_length(value, "name", 50, allow_none=False, allow_empty=False)


class AgencyDevices(Base):
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

    location = relationship("AgencyLocations", lazy="select")


class AgencyStorages(Base):
    """Storage units within a location."""

    __tablename__ = "agency_storages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agency_id: Mapped[int] = mapped_column(Integer, ForeignKey("agencies.id"), index=True)
    location_id: Mapped[int] = mapped_column(Integer, ForeignKey("agency_locations.id"), index=True)
    name: Mapped[str] = mapped_column(String(50))
    user_access_from: Mapped[bool] = mapped_column(Boolean, default=True)
    user_access_to: Mapped[bool] = mapped_column(Boolean, default=True)

    agency = relationship("Agencies", back_populates="storages", lazy="select")
    location = relationship("AgencyLocations", back_populates="storages", lazy="selectin")

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


class AgencyItemTags(Base):
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
