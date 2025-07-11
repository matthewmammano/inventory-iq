from datetime import datetime, timezone
from urllib.parse import urlparse

from sqlalchemy import JSON, event
from sqlalchemy.orm import validates

from app import db
from app.auth.models import UserItemPreferences, UserItemTags


class Items(db.Model):
    # true unique reference to the item
    id = db.Column(db.Integer, primary_key=True)
    # Universal Product Code, 12 digits (supposed to be unique)
    upc = db.Column(db.String(12))
    # active status of the item or soft deleted
    active = db.Column(db.Boolean, default=True, nullable=False)
    # first aid squad taking owndership of the item
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    # Store tag IDs as JSON array, defaulting to empty list
    tag_ids = db.Column(JSON, default=list, nullable=False)
    # 'individual', 'box', 'case', etc.
    increments = db.Column(db.String(50))
    # 'Bandage', 'Aspirin', 'Tourniquet', etc.
    name = db.Column(db.String(100), nullable=False)
    # image online URL to the item's image
    image = db.Column(db.String(255))
    last_accessed = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    action_logs = db.relationship("ActionLogs", backref="item", lazy=True)

    @property
    def tags(self):
        """Get actual tag objects for this item."""
        if not self.tag_ids:
            return []
        return UserItemTags.query.filter(
            UserItemTags.id.in_(self.tag_ids), UserItemTags.user_id == self.user_id
        ).all()

    # Create index on user_id and others
    __table_args__ = (
        db.Index("idx_user_upc", "user_id", "upc"),
        db.Index("idx_user_name", "user_id", "name"),
        db.Index("idx_user_last_accessed", "user_id", "last_accessed"),
    )

    def __repr__(self):
        return f"<Item {self.name}>"

    def add_tag(self, tag_id):
        """Add a tag ID to the list if not already present."""
        if self.tag_ids is None:
            self.tag_ids = []
        if tag_id not in self.tag_ids:
            self.tag_ids.append(tag_id)

    def remove_tag(self, tag_id):
        """Remove a tag ID from the list."""
        if self.tag_ids and tag_id in self.tag_ids:
            self.tag_ids.remove(tag_id)

    @validates("tag_ids")
    def validate_tag_ids(self, key, value):
        """Validate that tag_ids is a list of integers."""
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("tag_ids must be a list")
        # Validate all items are integers
        for item in value:
            if not isinstance(item, int):
                raise ValueError("All tag IDs must be integers")
        return value

    @staticmethod
    def calculate_upc_check_digit(upc11: str) -> str:
        digits = [int(d) for d in upc11]
        odd_sum = sum(digits[::2]) * 3
        even_sum = sum(digits[1::2])
        total = odd_sum + even_sum
        return str((10 - total % 10) % 10)

    @staticmethod
    def generate_upc(user_id: int, item_id: int) -> str:
        user_part = str(user_id)[-5:].zfill(5)  # Last 5 digits, pad if needed
        item_part = str(item_id)[-6:].zfill(6)  # Last 6 digits, pad if needed
        base = user_part + item_part  # Always 11 digits
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
        # Check if UPC already exists
        existing = Items.query.filter_by(upc=value).first()
        if existing and existing.id != getattr(self, "id", None):
            return None  # Set to None if duplicate
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
        db.ForeignKey("user_item_locations.id"),
        nullable=True,  # if Null, then RECOUNT, else transfer
    )
    to_location_id = db.Column(
        db.Integer,
        db.ForeignKey("user_item_locations.id"),
        nullable=True,  # if Null, then REMOVED, else normal transfer / RECOUNT
    )
    quantity_delta = db.Column(db.Integer, nullable=False)
    # if this action was performed by an admin (e.g., via the admin panel)
    admin_action = db.Column(db.Boolean, default=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    # Relationships
    from_location = db.relationship(
        "UserItemLocations",
        foreign_keys=[from_location_id],
        backref="from_location_logs",
        lazy=True,
    )
    to_location = db.relationship(
        "UserItemLocations",
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

    @validates("from_location_id", "to_location_id")
    def validate_locations(self, key, value):
        # Use the new value for the field being set, and the current value for the other
        from_id = value if key == "from_location_id" else self.from_location_id
        to_id = value if key == "to_location_id" else self.to_location_id
        if from_id is None and to_id is None:
            raise ValueError(
                "Both from_location_id and to_location_id cannot be null at the same time."
            )
        return value

    @property
    def is_recount(self):
        return self.from_location_id is None

    @property
    def is_transfer(self):
        return self.from_location_id is not None

    def process_action(self, db_session):
        """
        Update ItemLocationQuantities for this action and check for alerts.
        Returns: (updated_quantities, alerts)
        alerts: list of dicts, each with keys: location_id, alert_type, quantity
        """
        updated_quantities = {}
        alerts = []

        # Handle recount (from_location_id is None)
        if self.from_location_id is None and self.to_location_id:
            # Set quantity at TO location to quantity_delta
            qty_row = ItemLocationQuantities.query.filter_by(
                user_id=self.user_id,
                item_id=self.item_id,
                location_id=self.to_location_id,
            ).first()
            if not qty_row:
                qty_row = ItemLocationQuantities(
                    user_id=self.user_id,
                    item_id=self.item_id,
                    location_id=self.to_location_id,
                    quantity=self.quantity_delta,
                )
                db_session.add(qty_row)
            else:
                qty_row.quantity = self.quantity_delta
            updated_quantities[self.to_location_id] = qty_row.quantity

        # Handle transfer (from_location_id and to_location_id)
        elif self.from_location_id and self.to_location_id:
            # Decrement from FROM location
            from_qty_row = ItemLocationQuantities.query.filter_by(
                user_id=self.user_id,
                item_id=self.item_id,
                location_id=self.from_location_id,
            ).first()
            if not from_qty_row:
                from_qty_row = ItemLocationQuantities(
                    user_id=self.user_id,
                    item_id=self.item_id,
                    location_id=self.from_location_id,
                    quantity=0,
                )
                db_session.add(from_qty_row)
            from_qty_row.quantity = max(0, from_qty_row.quantity - self.quantity_delta)
            updated_quantities[self.from_location_id] = from_qty_row.quantity

            # Increment at TO location
            to_qty_row = ItemLocationQuantities.query.filter_by(
                user_id=self.user_id,
                item_id=self.item_id,
                location_id=self.to_location_id,
            ).first()
            if not to_qty_row:
                to_qty_row = ItemLocationQuantities(
                    user_id=self.user_id,
                    item_id=self.item_id,
                    location_id=self.to_location_id,
                    quantity=0,
                )
                db_session.add(to_qty_row)
            to_qty_row.quantity += self.quantity_delta
            updated_quantities[self.to_location_id] = to_qty_row.quantity

        # Handle REMOVED (to_location_id is None)
        elif self.from_location_id and self.to_location_id is None:
            # Remove from FROM location
            from_qty_row = ItemLocationQuantities.query.filter_by(
                user_id=self.user_id,
                item_id=self.item_id,
                location_id=self.from_location_id,
            ).first()
            if not from_qty_row:
                from_qty_row = ItemLocationQuantities(
                    user_id=self.user_id,
                    item_id=self.item_id,
                    location_id=self.from_location_id,
                    quantity=0,
                )
                db_session.add(from_qty_row)
            from_qty_row.quantity = max(0, from_qty_row.quantity - self.quantity_delta)
            updated_quantities[self.from_location_id] = from_qty_row.quantity

        # Check for alerts (low stock or over max) at all affected locations
        prefs = UserItemPreferences.query.filter_by(
            user_id=self.user_id, item_id=self.item_id
        ).first()
        for loc_id, qty in updated_quantities.items():
            if prefs:
                if prefs.min_quantity is not None and qty < prefs.min_quantity:
                    alerts.append(
                        {
                            "location_id": loc_id,
                            "alert_type": "low_stock",
                            "quantity": qty,
                            "min_quantity": prefs.min_quantity,
                        }
                    )
                if prefs.max_quantity is not None and qty > prefs.max_quantity:
                    alerts.append(
                        {
                            "location_id": loc_id,
                            "alert_type": "over_max",
                            "quantity": qty,
                            "max_quantity": prefs.max_quantity,
                        }
                    )
        return updated_quantities, alerts


class ItemLocationQuantities(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False, index=True
    )
    item_id = db.Column(
        db.Integer, db.ForeignKey("items.id"), nullable=False, index=True
    )
    location_id = db.Column(
        db.Integer, db.ForeignKey("user_item_locations.id"), nullable=False, index=True
    )
    quantity = db.Column(db.Integer, nullable=False, default=0)

    __table_args__ = (
        db.UniqueConstraint(
            "user_id", "item_id", "location_id", name="uq_user_item_location"
        ),
    )

    def __repr__(self):
        return f"<ItemLocationQuantities user={self.user_id} item={self.item_id} location={self.location_id} qty={self.quantity}>"


# TODO RED: does this auto go? idk if it should? maybe just listen for user specifying the upc? maybe only i do it? bc they need mailed / re-printed cards ANYWAYS!
# Auto-generate UPC after item is inserted into database
@event.listens_for(Items, "after_insert")
def generate_upc_after_insert(mapper, connection, target):
    """Automatically generate UPC after item is inserted if no UPC was provided."""
    if not target.upc and target.id and target.user_id:
        upc = Items.generate_upc(target.user_id, target.id)
        # Update the item with the generated UPC
        connection.execute(
            Items.__table__.update().where(Items.id == target.id).values(upc=upc)
        )
        # Update the target object so it reflects the new UPC
        target.upc = upc
