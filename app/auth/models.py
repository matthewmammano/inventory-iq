from datetime import datetime, timezone

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from app import db


class Users(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    display_name = db.Column(db.String(50), unique=True, nullable=False)
    email = db.Column(db.String(128), unique=True, nullable=False)
    password = db.Column(db.String(128))
    pin = db.Column(db.String(4), nullable=False, default="1234")
    image = db.Column(db.String(255))
    notes = db.Column(db.Text)
    timezone = db.Column(db.String(50), default="America/New_York", nullable=False)
    created_at = db.Column(
        db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    active = db.Column(db.Boolean, default=True, nullable=False)

    # Relationships
    items = db.relationship("Items", backref="user", lazy=True)
    logs = db.relationship("ActionLogs", backref="user", lazy=True)
    settings = db.relationship("UserSettings", backref="user", lazy=True)
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


class UserSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False, index=True
    )
    # Email for alerts
    contact_info = db.Column(db.String(255), nullable=False)
    # Alert Types
    alert_on_low_stock = db.Column(db.Boolean, default=True, nullable=False)
    alert_on_scan = db.Column(db.Boolean, default=False, nullable=False)
    # Scheduled alerts
    daily_summary = db.Column(db.Boolean, default=False, nullable=False)
    weekly_report = db.Column(db.Boolean, default=True, nullable=False)

    def __repr__(self):
        return f"<UserSettings {self.user_id}>"


# TODO YELLOW: add a UserLocations and UserStorages (as subclass of UserLocations) for Tom Alexander's hospital
class UserItemLocations(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False, index=True
    )
    location_name = db.Column(db.String(50), nullable=False)
    user_access_from = db.Column(db.Boolean, default=True, nullable=False)
    user_access_to = db.Column(db.Boolean, default=True, nullable=False)

    def __repr__(self):
        return f"<UserItemLocations {self.location_name}>"


class UserItemTags(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False, index=True
    )
    tag_name = db.Column(db.String(50), nullable=False)

    def __repr__(self):
        return f"<UserItemTags {self.tag_name}>"


class UserItemPreferences(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False, index=True
    )
    item_id = db.Column(
        db.Integer, db.ForeignKey("items.id"), nullable=False, index=True
    )
    min_quantity = db.Column(db.Integer, nullable=True)  # Alert when below this
    max_quantity = db.Column(db.Integer, nullable=True)  # Desired/reorder amount

    __table_args__ = (
        db.UniqueConstraint("user_id", "item_id", name="uq_user_item_pref"),
    )

    def __repr__(self):
        return f"<UserItemPreferences user={self.user_id} item={self.item_id}>"
