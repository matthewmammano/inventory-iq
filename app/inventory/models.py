from datetime import datetime, timezone
from urllib.parse import urlparse

from sqlalchemy.orm import validates

from app import db


class Items(db.Model):
    # true unique reference to the item
    id = db.Column(db.Integer, primary_key=True)
    # Universal Product Code, 12 digits (supposed to be unique)
    upc = db.Column(db.String(12))
    # active status of the item or soft deleted
    active = db.Column(db.Boolean, default=True, nullable=False)
    # first aid squad taking owndership of the item
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    category_id = db.Column(
        db.Integer, db.ForeignKey("user_categories.id"), nullable=False
    )
    # 'individual', 'box', 'case', etc.
    increments = db.Column(db.String(50))
    # 'Bandage', 'Aspirin', 'Tourniquet', etc.
    name = db.Column(db.String(100), nullable=False)
    # for low stock and reorders
    min_quantity = db.Column(db.Integer, nullable=False)
    # for reorder stock
    max_quantity = db.Column(db.Integer, nullable=False)
    # quantity is updated on EVERY change in log (to that item)
    quantity = db.Column(db.Integer)
    # image online URL to the item's image
    image = db.Column(db.String(255))
    last_accessed = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    category = db.relationship("UserCategories", backref="item", lazy=True)
    action_logs = db.relationship("ActionLogs", backref="item", lazy=True)

    # Create index on user_id and others
    __table_args__ = (
        db.Index("idx_user_upc", "user_id", "upc"),
        db.Index("idx_user_category", "user_id", "category_id"),
        db.Index("idx_user_name", "user_id", "name"),
        db.Index("idx_user_quantity", "user_id", "quantity"),
        db.Index("idx_user_last_accessed", "user_id", "last_accessed"),
    )

    def __repr__(self):
        return f"<Item {self.name}>"

    @staticmethod
    def calculate_upc_check_digit(upc11: str) -> str:
        digits = [int(d) for d in upc11]
        odd_sum = sum(digits[::2]) * 3
        even_sum = sum(digits[1::2])
        total = odd_sum + even_sum
        return str((10 - total % 10) % 10)

    @staticmethod
    def generate_upc(user_id: int, item_id: int) -> str:
        base = str(user_id).zfill(5) + str(item_id).zfill(4)
        return base + Items.calculate_upc_check_digit(base)

    @validates("upc")
    def validate_upc(self, key, value):
        if not value:
            return value
        if not value.isdigit() or len(value) != 12:
            raise ValueError("UPC must be a 12-digit number.")
        # Validate check digit
        calculated_check = self.calculate_upc_check_digit(value[:11])
        if calculated_check != value[11]:
            raise ValueError("Invalid UPC check digit.")
        return value

    @validates("min_quantity", "max_quantity")
    def validate_quantity(self, key, value):
        """Ensure min_quantity is less than or equal to max_quantity."""
        if key == "min_quantity" and value < 0:
            raise ValueError("Minimum quantity cannot be negative.")
        if key == "max_quantity" and value < 0:
            raise ValueError("Maximum quantity cannot be negative.")
        # Only check relationship if both are set
        min_q = value if key == "min_quantity" else self.min_quantity
        max_q = value if key == "max_quantity" else self.max_quantity
        if min_q is not None and max_q is not None and min_q > max_q:
            raise ValueError(
                "Minimum quantity cannot be greater than maximum quantity."
            )
        return value

    @validates("image")
    def validate_image(self, key, value):
        """Validate image URL format."""
        if value:
            parsed = urlparse(value)
            if not (
                parsed.scheme and parsed.scheme in ("http", "https") and parsed.netloc
            ):
                raise ValueError("Image URL must be a valid URL.")
        return value


class ActionLogs(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(
        db.DateTime, default=lambda: datetime.now(timezone.utc)
    )  # TODO GREEN: make sure ALL timezones are in UTC
    item_id = db.Column(db.Integer, db.ForeignKey("items.id"))
    from_location_id = db.Column(
        db.Integer,
        db.ForeignKey("user_locations.id"),
        nullable=True,  # if Null, then recount, else transfer
    )
    to_location_id = db.Column(
        db.Integer, db.ForeignKey("user_locations.id"), nullable=False
    )
    quantity_delta = db.Column(db.Integer, nullable=False)
    # if this action was performed by an admin (e.g., via the admin panel)
    admin_action = db.Column(db.Boolean, default=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    # Relationships
    from_location = db.relationship(
        "UserLocations",
        foreign_keys=[from_location_id],
        backref="from_location_logs",
        lazy=True,
    )
    to_location = db.relationship(
        "UserLocations",
        foreign_keys=[to_location_id],
        backref="to_location_logs",
        lazy=True,
    )

    # Create index on user_id and others
    __table_args__ = (
        db.Index("idx_user_timestamp", "user_id", "timestamp"),
        db.Index("idx_user_item_id", "user_id", "item_id"),
        db.Index("idx_user_from_location", "user_id", "from_location_id"),
        db.Index("idx_user_to_location", "user_id", "to_location_id"),
    )

    def __repr__(self):
        return f"<ActionLog {self.from_location} to {self.to_location}>"

    @validates("quantity_delta")
    def validate_quantity_delta(self, key, value):
        """Validate quantity_delta is a positive integer."""
        if not isinstance(value, int) or value < 0:
            raise ValueError("Quantity delta must be a non-negative integer.")
        return value

    @property
    def is_recount(self):
        return self.from_location_id is None

    @property
    def is_transfer(self):
        return self.from_location_id is not None
