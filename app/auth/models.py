from datetime import datetime, timezone

from flask_login import UserMixin
from sqlalchemy.orm import validates
from werkzeug.security import check_password_hash, generate_password_hash

from app import db
from app.helpers.model_validate import (
    validate_email_format,
    validate_image_url,
    validate_string_length,
    validate_timezone,
)


class Users(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    display_name = db.Column(db.String(50), unique=True, nullable=False)
    email = db.Column(db.String(128), unique=True, nullable=False)
    password = db.Column(db.String(128))
    pin = db.Column(db.String(4), nullable=False, default="1234")
    image = db.Column(db.String(255))
    notes = db.Column(db.Text)
    timezone = db.Column(db.String(50), default="America/New_York", nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)

    # Relationships
    items = db.relationship("Items", backref="user", lazy=True)
    logs = db.relationship("ActionLogs", backref="user", lazy=True)
    emails = db.relationship("UserEmails", backref="user", lazy=True)
    alerts = db.relationship("UserAlerts", backref="user", lazy=True)
    item_tags = db.relationship("UserItemTags", backref="user", lazy=True)
    locations = db.relationship("UserItemLocations", backref="user", lazy=True)

    def set_password(self, password):
        """Set the password hash."""
        self.password = generate_password_hash(password)

    def check_password(self, password):
        """Check the password hash."""
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
    def validate_display_name(self, key, value):
        """Validate display name."""
        return validate_string_length(value, "display_name", 50, allow_none=False, allow_empty=False)

    @validates("email")
    def validate_email(self, key, value):
        """Validate email format and length."""
        if value:
            value = validate_email_format(value)
            validate_string_length(value, "email", 128, allow_none=False, allow_empty=False)
        return value

    @validates("pin")
    def validate_pin(self, key, value):
        """Validate PIN format."""
        if not value or not value.isdigit() or len(value) != 4:
            raise ValueError("PIN must be exactly 4 digits")
        return value

    @validates("image")
    def validate_image(self, key, value):
        """Validate image URL format."""
        return validate_image_url(value)

    @validates("timezone")
    def validate_timezone_field(self, key, value):
        """Validate timezone."""
        return validate_timezone(value)


class UserEmails(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    email = db.Column(db.String(128), unique=True, nullable=False)

    @validates("email")
    def validate_contact_info(self, key, value):
        """Validate email."""
        if value:
            value = validate_email_format(value)
            validate_string_length(value, "email", 255, allow_none=False, allow_empty=False)
        return value


class UserAlerts(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    email_id = db.Column(db.Integer, db.ForeignKey("user_emails.id"), nullable=False)
    # Alert Types
    alert_on_low_stock = db.Column(db.Boolean, default=True, nullable=False)
    alert_on_scan = db.Column(db.Boolean, default=False, nullable=False)
    # Scheduled alerts
    daily_summary = db.Column(db.Boolean, default=False, nullable=False)
    weekly_report = db.Column(db.Boolean, default=True, nullable=False)

    def __repr__(self):
        return f"<UserAlerts {self.user_id}>"


# TODO YELLOW: add a UserLocations and UserStorages (as subclass of UserLocations) for Tom's hospital
class UserItemLocations(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    location_name = db.Column(db.String(50), nullable=False)
    user_access_from = db.Column(db.Boolean, default=True, nullable=False)
    user_access_to = db.Column(db.Boolean, default=True, nullable=False)

    def __repr__(self):
        return f"<UserItemLocations {self.location_name}>"

    @validates("location_name")
    def validate_location_name(self, key, value):
        """Validate location name."""
        return validate_string_length(value, "location_name", 50, allow_none=False, allow_empty=False)


class UserItemTags(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    tag_name = db.Column(db.String(50), nullable=False)

    def __repr__(self):
        return f"<UserItemTags {self.tag_name}>"

    @validates("tag_name")
    def validate_tag_name(self, key, value):
        """Validate tag name."""
        return validate_string_length(value, "tag_name", 50, allow_none=False, allow_empty=False)


class UserItemAlerts(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    item_id = db.Column(db.Integer, db.ForeignKey("items.id"), nullable=False, index=True)

    __table_args__ = (db.UniqueConstraint("user_id", "item_id", name="uq_user_item_pref"),)

    def __repr__(self):
        return f"<UserItemAlerts user={self.user_id} item={self.item_id}>"
