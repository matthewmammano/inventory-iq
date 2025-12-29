import re
import string
from datetime import UTC, datetime
from typing import Any

from flask_login import UserMixin
from loguru import logger
from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates
from werkzeug.security import check_password_hash, generate_password_hash

from app.db import Base
from app.utils.model_validate import (
    validate_email_with_length,
    validate_image_url,
    validate_string_length,
    validate_timezone,
)

DEFAULT_TEXT = "#000000"
WHITE_TEXT = "#ffffff"


class Users(Base, UserMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    display_name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    password: Mapped[str | None] = mapped_column(Text)
    pin: Mapped[str] = mapped_column(String(4), nullable=False, default="1234")
    image: Mapped[str | None] = mapped_column(String(255))
    user_count_allow: Mapped[bool] = mapped_column(Boolean, default=False)
    user_restock_allow: Mapped[bool] = mapped_column(Boolean, default=False)
    user_take_allow: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(Text)
    timezone: Mapped[str] = mapped_column(
        String(50), default="America/New_York", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), nullable=False
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Relationships (deferred to string names to avoid circular imports)
    items = relationship("Items", backref="user", lazy="selectin")
    logs = relationship("ActionLogs", backref="user", lazy="selectin")
    emails = relationship("UserEmails", backref="user", lazy="selectin")
    alerts = relationship("UserAlerts", backref="user", lazy="selectin")
    item_tags = relationship("UserItemTags", backref="user", lazy="selectin")
    locations = relationship("UserItemLocations", backref="user", lazy="selectin")

    def set_password(self, password: str) -> None:
        """Set the password hash."""
        self.password = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        """Check the password hash."""
        if not self.password:
            return False
        return check_password_hash(self.password, password)

    def __repr__(self):
        return f"<User {self.display_name}>"

    @property
    def user_context(self):
        """Return the user context for Flask-Login."""
        return {
            "user_id": self.id,
            "display_name": self.display_name,
            "image": self.image,
            "timezone": self.timezone,
        }

    @validates("display_name")
    def validate_display_name(self, key: str, value: str) -> str | None:
        """Validate display name."""
        return validate_string_length(
            value, "display_name", 50, allow_none=False, allow_empty=False
        )

    @validates("email")
    def validate_email(self, key: str, value: str | None) -> str | None:
        """Validate email format and length."""
        return validate_email_with_length(value, max_length=128, allow_none=False)

    @validates("pin")
    def validate_pin(self, key: str, value: str) -> str:
        """Validate PIN format."""
        if not value or not value.isdigit() or len(value) != 4:
            raise ValueError("PIN must be exactly 4 digits")
        return value

    @validates("image")
    def validate_image(self, key: str, value: str | None) -> str | None:
        """Validate image URL format."""
        return validate_image_url(value)

    @validates("timezone")
    def validate_timezone_field(self, key: str, value: str) -> str:
        """Validate timezone."""
        return validate_timezone(value)


class UserEmails(Base):
    __tablename__ = "user_emails"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), index=True, nullable=False
    )
    email: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)

    @validates("email")
    def validate_email(self, key: str, value: str | None) -> str | None:
        """Validate email."""
        return validate_email_with_length(value, max_length=255, allow_none=False)


class UserAlerts(Base):
    __tablename__ = "user_alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), index=True, nullable=False
    )
    email_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("user_emails.id"), nullable=False
    )

    low_stock_days: Mapped[int] = mapped_column(Integer, default=14, nullable=False)
    rare_scan_days: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    zero_stock: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    count_last_days: Mapped[int | None] = mapped_column(
        Integer, default=90, nullable=True
    )

    daily_summary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    weekly_summary: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    monthly_summary: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    quarterly_summary: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    yearly_summary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    alert_grouping_hours: Mapped[int] = mapped_column(
        Integer, default=24, nullable=False
    )
    alert_delivery_hour: Mapped[int] = mapped_column(Integer, default=8, nullable=False)

    pending_alerts: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, nullable=False
    )
    last_sent: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # GREEN: Add critical level classification system for inventory items (RED/YELLOW/GREEN priority)
    # This would allow different alert thresholds based on item criticality:
    # - RED: Life-saving (Narcan, O2, AED pads) - immediate alerts
    # - YELLOW: Important (bandages, splints) - standard alerts
    # - GREEN: Nice-to-have (cleaning supplies) - relaxed alerts

    def __repr__(self):
        return f"<UserAlerts {self.user_id}>"


# TODO-3 TOM: add a UserLocations and UserStorages (as subclass of UserLocations) for Tom's hospital


class UserItemLocations(Base):
    __tablename__ = "user_item_locations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    user_access_from: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    user_access_to: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    def __repr__(self):
        return f"<UserItemLocations {self.name}>"

    @validates("name")
    def validate_location_name(self, key: str, value: str) -> str | None:
        """Validate location name."""
        return validate_string_length(
            value, "name", 50, allow_none=False, allow_empty=False
        )


class UserItemTags(Base):
    __tablename__ = "user_item_tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), index=True, nullable=False
    )
    tag_name: Mapped[str] = mapped_column(String(50), nullable=False)
    color: Mapped[str] = mapped_column(
        String(7), default="#3b82f6"
    )  # Default blue color

    @property
    def text_color(self):
        """Calculate contrasting text color (black or white) based on background color brightness."""
        color = (self.color or "").lstrip("#")
        if len(color) != 6:
            logger.warning(
                "Missing/invalid tag color %r; defaulting text color to black",
                self.color,
            )
            return DEFAULT_TEXT

        if any(c not in string.hexdigits for c in color):
            logger.debug(
                "Non-hex tag color %r; defaulting text color to black", self.color
            )
            return DEFAULT_TEXT

        r, g, b = int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)

        brightness = r * 0.299 + g * 0.587 + b * 0.114
        return WHITE_TEXT if brightness < 128 else DEFAULT_TEXT

    def __repr__(self):
        return f"<UserItemTags {self.tag_name}>"

    @validates("tag_name")
    def validate_tag_name(self, key: str, value: str) -> str | None:
        """Validate tag name."""
        return validate_string_length(
            value, "tag_name", 50, allow_none=False, allow_empty=False
        )

    @validates("color")
    def validate_color(self, _key: str, value: str | None) -> str:
        """Validate color is valid hex format (#rrggbb)."""
        if value is None:
            return "#3b82f6"
        if not isinstance(value, str):
            raise TypeError("Color must be a string")
        value = value.strip()
        if not re.match(r"^#[0-9A-Fa-f]{6}$", value):
            raise ValueError("Color must be valid hex format: #rrggbb")
        return value.upper()
