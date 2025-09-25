import logging
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import JSON, event
from sqlalchemy.orm import validates

from app import db
from app.alerts.detection_service import AlertDetectionService
from app.auth.models import UserItemTags
from app.utils.model_validate import (
    validate_image_url,
    validate_non_negative_integer,
    validate_positive_integer,
    validate_string_length,
    validate_tag_id_type,
)
from app.utils.timezone_utils import convert_utc_to_local

# TODO GREEN: update...
# - to NEW version of SQLAlchemy


class OperationType(Enum):
    count = "COUNT"
    restock = "RESTOCK"
    takeout = "TAKEOUT"
    transfer = "TRANSFER"


def get_or_create_item_location_quantity(db_session, user_id, item_id, location_id):
    """Get or create ItemLocationQuantities database row for tracking inventory at specific location."""
    qty_row = ItemLocationQuantities.query.filter_by(user_id=user_id, item_id=item_id, location_id=location_id).first()
    if not qty_row:
        qty_row = ItemLocationQuantities(user_id=user_id, item_id=item_id, location_id=location_id, quantity=0)
        db_session.add(qty_row)
    return qty_row


class Items(db.Model):
    id = db.Column(db.Integer, primary_key=True)  # true unique reference to the item
    upc = db.Column(db.String(12))  # 12 digits (unique per user)
    active = db.Column(db.Boolean, default=True, nullable=False)

    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)  # squad
    tag_ids = db.Column(JSON, default=list, nullable=False)  # Store tag IDs, default []

    increments = db.Column(db.String(50))  # 'individual', 'box', 'case', etc.
    name = db.Column(db.String(100), nullable=False)  # 'Bandage', 'Aspirin', etc.
    image = db.Column(db.String(1024))  # image online URL to the item's image
    last_accessed = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    min_quantity = db.Column(db.Integer, nullable=True)  # alert when below this
    max_quantity = db.Column(db.Integer, nullable=True)  # desired/reorder amount
    batch_size = db.Column(db.Integer, nullable=True)  # batch amount for restocking
    expiration_days = db.Column(db.Integer, nullable=True)  # approx. days until expiration for perishable items
    restock_delivery_days = db.Column(db.Integer, nullable=True)  # days to expect delivery after restock order
    prior_daily_usage = db.Column(db.Float, nullable=True)  # manual prior knowledge of daily usage rate

    # TODO ORANGE ANDY: Add expiration date tracking for items -> MESSAGE ANDY WELSH PURCHASE
    # - Add expiry_date field to Items model
    # - Create expiration alerts in admin dashboard
    # - Filter expired items in inventory views
    # - Add expiration-based reorder suggestions

    # Relationships
    action_logs = db.relationship("ActionLogs", backref="item", lazy=True)

    @property
    def tags(self):
        """Get actual tag objects for this item."""
        if not self.tag_ids:
            return []
        return UserItemTags.query.filter(UserItemTags.id.in_(self.tag_ids), UserItemTags.user_id == self.user_id).all()

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
        validate_tag_id_type(tag_id)
        if self.tag_ids is None:
            self.tag_ids = []
        if tag_id not in self.tag_ids:
            self.tag_ids.append(tag_id)

    def remove_tag(self, tag_id):
        """Remove a tag ID from the list."""
        validate_tag_id_type(tag_id)
        if self.tag_ids and tag_id in self.tag_ids:
            self.tag_ids.remove(tag_id)

    def get_last_accessed_local(self, user_timezone: str):
        """Get last_accessed converted to user's local timezone."""
        return convert_utc_to_local(self.last_accessed, user_timezone)

    @validates("tag_ids")
    def validate_tag_ids(self, key, value):
        """Validate that tag_ids is a list of integers."""
        if value is None:
            return []
        if not isinstance(value, list):
            logging.error(
                f"Tag validation error for item {getattr(self, 'id', 'new')}: tag_ids must be a list, got {type(value)}"
            )
            raise ValueError("tag_ids must be a list")
        # Validate all items are integers
        for item in value:
            if not isinstance(item, int):
                logging.error(
                    f"Tag validation error for item {getattr(self, 'id', 'new')}: tag ID must be integer, got {type(item)}"
                )
                raise ValueError("All tag IDs must be integers")
            try:
                validate_tag_id_type(item)
            except ValueError as e:
                logging.error(f"Tag validation error for item {getattr(self, 'id', 'new')}: {e}")
                raise
        return value

    @validates("name")
    def validate_name(self, key, value):
        """Validate name field."""
        try:
            return validate_string_length(value, "name", 100, allow_none=False, allow_empty=False)
        except ValueError as e:
            logging.error(f"Name validation error for item {getattr(self, 'id', 'new')}: {e}")
            raise

    @validates("increments")
    def validate_increments(self, key, value):
        """Validate increments field."""
        try:
            return validate_string_length(value, "increments", 50, allow_none=True, allow_empty=True)
        except ValueError as e:
            logging.error(f"Increments validation error for item {getattr(self, 'id', 'new')}: {e}")
            raise

    @validates("min_quantity", "max_quantity", "batch_size", "expiration_days", "restock_delivery_days")
    def validate_positive_integers(self, key, value):
        """Validate positive integer fields."""
        try:
            return validate_positive_integer(value, key, allow_none=True)
        except ValueError as e:
            logging.error(f"Integer validation error for item {getattr(self, 'id', 'new')} field '{key}': {e}")
            raise

    @validates("prior_daily_usage")
    def validate_prior_daily_usage(self, key, value):
        """Validate prior daily usage is a non-negative float."""
        if value is None:
            return None
        try:
            value = float(value)
            if value < 0:
                raise ValueError("Prior daily usage must be non-negative")
            return value
        except (ValueError, TypeError) as e:
            logging.error(f"Prior daily usage validation error for item {getattr(self, 'id', 'new')}: {e}")
            raise ValueError("Prior daily usage must be a non-negative number")

    @validates("image")
    def validate_image(self, key, value):
        """Validate image URL format."""
        try:
            return validate_image_url(value)
        except ValueError as e:
            logging.error(f"Image URL validation error for item {getattr(self, 'id', 'new')}: {e}")
            raise

    @staticmethod
    def calculate_upc_check_digit(upc11: str) -> str:
        digits = [int(d) for d in upc11]
        odd_sum = sum(digits[::2]) * 3
        even_sum = sum(digits[1::2])
        total = odd_sum + even_sum
        return str((10 - total % 10) % 10)

    @staticmethod
    def generate_upc(user_id: int) -> str:
        halfway_point = "500000000000"  # start auto-generation at halfway point

        largest_upc = (
            Items.query.filter(Items.user_id == user_id, Items.upc >= halfway_point).order_by(Items.upc.desc()).first()
        )

        if largest_upc:
            base_11 = largest_upc.upc[:11]  # Remove check digit
            next_number = int(base_11) + 1
            next_base = str(next_number).zfill(11)
        else:
            next_base = halfway_point[:11]

        new_upc = next_base + Items.calculate_upc_check_digit(next_base)

        if Items.query.filter_by(upc=new_upc).first():
            logging.error(
                f"UPC generation failure: Generated UPC {new_upc} already exists for user {user_id} - UPC space may be exhausted"
            )
            raise ValueError(f"Generated UPC {new_upc} already exists - UPC space may be exhausted")

        return new_upc

    @validates("upc")
    def validate_upc(self, key, value):
        # Allow None/empty values to pass through for auto-generation
        if not value:
            return None
        if not isinstance(value, str):
            logging.error(
                f"UPC validation error for item {getattr(self, 'id', 'new')}: UPC must be a string, got {type(value)}"
            )
            raise ValueError("UPC must be a string.")
        if not value or value.strip() == "":
            return None
        if not value.isdigit() or len(value) != 12:
            logging.error(
                f"UPC validation error for item {getattr(self, 'id', 'new')}: Invalid UPC format '{value}' - must be 12 digits"
            )
            raise ValueError("UPC must be a 12-digit number.")
        # Validate check digit
        calculated_check = self.calculate_upc_check_digit(value[:11])
        if calculated_check != value[11]:
            logging.error(
                f"UPC validation error for item {getattr(self, 'id', 'new')}: Invalid check digit for UPC '{value}'"
            )
            raise ValueError("Invalid UPC check digit.")
        # Check if UPC already exists
        try:
            existing = Items.query.filter_by(upc=value, user_id=self.user_id).first()
            if existing and existing.id != self.id:
                logging.error(
                    f"UPC validation error: UPC '{value}' already exists for user {self.user_id} on item {existing.id}"
                )
                raise ValueError("UPC already exists for another item in your account.")
        except Exception as e:
            if "already exists" in str(e):
                raise
            logging.error(f"Database error during UPC uniqueness check for item {getattr(self, 'id', 'new')}: {e}")
            raise ValueError("Database error during UPC validation")
        return value


class ActionLogs(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    item_id = db.Column(db.Integer, db.ForeignKey("items.id"))
    operation_type = db.Column(db.Enum(OperationType), nullable=False)
    from_location_id = db.Column(
        db.Integer,
        db.ForeignKey("user_item_locations.id"),
        nullable=True,  # null for COUNT/RESTOCK operations
    )
    to_location_id = db.Column(
        db.Integer,
        db.ForeignKey("user_item_locations.id"),
        nullable=True,  # null for TAKEOUT operations
    )

    quantity_delta = db.Column(db.Integer, nullable=False)
    # if this action was performed by an admin (e.g., via the admin panel)
    admin_action = db.Column(db.Boolean, default=False)
    time_scanned = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

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
        db.Index("idx_user_item_id", "user_id", "item_id"),
        db.Index("idx_user_from_location", "user_id", "from_location_id"),
        db.Index("idx_user_to_location", "user_id", "to_location_id"),
    )

    def __repr__(self):
        return f"<ActionLog {self.from_location} to {self.to_location}>"

    @validates("quantity_delta")
    def validate_quantity_delta(self, key, value):
        """Validate quantity_delta is a non-negative integer."""
        try:
            return validate_non_negative_integer(value, "quantity_delta", allow_none=False)
        except ValueError as e:
            logging.error(f"Quantity delta validation error for action log {getattr(self, 'id', 'new')}: {e}")
            raise

    @property
    def is_count(self):
        return self.operation_type == OperationType.count

    @property
    def is_restock(self):
        return self.operation_type == OperationType.restock

    @property
    def is_transfer(self):
        return self.operation_type == OperationType.transfer

    @property
    def is_takeout(self):
        return self.operation_type == OperationType.takeout

    def get_time_scanned_local(self, user_timezone: str):
        """Get time_scanned converted to user's local timezone."""
        return convert_utc_to_local(self.time_scanned, user_timezone)

    def process_action(self, db_session):
        """
        Update ItemLocationQuantities and check for alerts.

        Negative quantities are allowed and indicate data quality issues
        that require admin attention via COUNT operations.

        Returns:
            tuple: (updated_quantities_dict, alerts_list)
        """
        updated_quantities = {}
        previous_quantities = {}

        # Handle FROM location (subtract quantity)
        if self.from_location_id:
            from_qty = get_or_create_item_location_quantity(
                db_session, self.user_id, self.item_id, self.from_location_id
            )
            previous_quantities[self.from_location_id] = from_qty.quantity
            from_qty.quantity = from_qty.quantity - self.quantity_delta
            updated_quantities[self.from_location_id] = from_qty.quantity

        # Handle TO location (add/set quantity)
        if self.to_location_id:
            to_qty = get_or_create_item_location_quantity(db_session, self.user_id, self.item_id, self.to_location_id)
            previous_quantities[self.to_location_id] = to_qty.quantity

            if self.operation_type == OperationType.count:
                # COUNT operations set absolute quantity (ground truth)
                to_qty.quantity = self.quantity_delta
            else:
                # RESTOCK, TRANSFER operations add to existing quantity
                to_qty.quantity = to_qty.quantity + self.quantity_delta

            updated_quantities[self.to_location_id] = to_qty.quantity

        # Check for alerts (non-blocking to avoid failing inventory operations)
        try:
            alerts = AlertDetectionService.check_quantity_alerts(
                self.user_id, self.item_id, updated_quantities, previous_quantities, self.admin_action
            )
        except Exception as e:
            logging.error(f"Alert detection failed for ActionLog {self.id}: {e}")
            alerts = []  # Don't fail the operation if alerts fail

        return updated_quantities, alerts


class ItemLocationQuantities(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    item_id = db.Column(db.Integer, db.ForeignKey("items.id"), nullable=False, index=True)
    location_id = db.Column(db.Integer, db.ForeignKey("user_item_locations.id"), nullable=False, index=True)
    quantity = db.Column(db.Integer, nullable=False, default=0)  # allows negative for calculations!

    __table_args__ = (db.UniqueConstraint("user_id", "item_id", "location_id", name="uq_user_item_location"),)

    def __repr__(self):
        return f"<ItemLocationQuantities user={self.user_id} item={self.item_id} location={self.location_id} qty={self.quantity}>"


@event.listens_for(Items, "before_insert")
def generate_upc_before_insert(mapper, connection, target):
    """Automatically generate UPC after item is inserted if no UPC was provided."""
    if not target.upc and target.user_id:
        try:
            target.upc = Items.generate_upc(target.user_id)
        except Exception as e:
            logging.error(f"UPC generation failure during item insert for user {target.user_id}: {e}")
            raise
