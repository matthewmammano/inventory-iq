from datetime import UTC, datetime
from typing import Any

from loguru import logger
from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    event,
    select,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import (
    Mapped,
    mapped_column,
    object_session,
    relationship,
    validates,
)

from app.db import Base
from app.inventory.constants import UPC_GENERATION_START, OperationType
from app.inventory.data.quantity import (
    apply_action_to_quantities,
    calculate_item_quantities,
)
from app.utils.model_validate import (
    validate_image_url,
    validate_non_negative_integer,
    validate_positive_integer,
    validate_string_length,
    validate_tag_id_type,
)
from app.utils.timezone_utils import convert_utc_to_local


class Items(Base):
    __tablename__ = "items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    upc: Mapped[str | None] = mapped_column(String(12))
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    tag_ids: Mapped[list[int]] = mapped_column(JSON, default=list, nullable=False)  # type: ignore[name-defined]

    increments: Mapped[str | None] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    image: Mapped[str | None] = mapped_column(String(1024))
    last_accessed: Mapped[datetime | None] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC)
    )

    min_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    batch_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expiration_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    restock_delivery_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prior_daily_usage: Mapped[float | None] = mapped_column(Float, nullable=True)
    # TODO-4 ANDY: Add expiration date tracking for items -> MESSAGE ANDY WELSH PURCHASE
    # - Add expiry_date field to Items model
    # - Create expiration alerts in admin dashboard
    # - Filter expired items in inventory views
    # - Add expiration-based reorder suggestions
    # Relationships
    action_logs = relationship("ActionLogs", back_populates="item", lazy="selectin")

    # Indexes
    __table_args__ = (
        Index("idx_user_upc", "user_id", "upc"),
        Index("idx_user_name", "user_id", "name"),
        Index("idx_user_last_accessed", "user_id", "last_accessed"),
    )

    def __repr__(self) -> str:
        return f"<Item {self.name}>"

    def add_tag(self, tag_id: int) -> None:
        validate_tag_id_type(tag_id)
        if self.tag_ids is None:
            self.tag_ids = []
        if tag_id not in self.tag_ids:
            self.tag_ids.append(tag_id)

    def remove_tag(self, tag_id: int) -> None:
        validate_tag_id_type(tag_id)
        if self.tag_ids and tag_id in self.tag_ids:
            self.tag_ids.remove(tag_id)

    def get_last_accessed_local(self, user_timezone: str) -> datetime | None:
        if self.last_accessed is None:
            return None
        return convert_utc_to_local(self.last_accessed, user_timezone)

    @validates("tag_ids")
    def validate_tag_ids(self, key: str, value: list[int]) -> list[int]:
        if value is None:
            return []
        if not isinstance(value, list):
            logger.error(
                f"Tag validation error for item {getattr(self, 'id', 'new')}: tag_ids must be a list, got {type(value)}"
            )
            raise ValueError("tag_ids must be a list")
        for item in value:
            if not isinstance(item, int):
                logger.error(
                    f"Tag validation error for item {getattr(self, 'id', 'new')}: tag ID must be integer, got {type(item)}"
                )
                raise ValueError("All tag IDs must be integers")
            try:
                validate_tag_id_type(item)
            except ValueError as e:
                logger.exception(
                    f"Tag validation error for item {getattr(self, 'id', 'new')}: {e}"
                )
                raise
        return value

    @validates("name")
    def validate_name(self, key: str, value: str | None) -> str | None:
        try:
            return validate_string_length(
                value, "name", 100, allow_none=False, allow_empty=False
            )
        except ValueError as e:
            logger.exception(
                f"Name validation error for item {getattr(self, 'id', 'new')}: {e}"
            )
            raise

    @validates("increments")
    def validate_increments(self, key: str, value: str | None) -> str | None:
        try:
            return validate_string_length(
                value, "increments", 50, allow_none=True, allow_empty=True
            )
        except ValueError as e:
            logger.exception(
                f"Increments validation error for item {getattr(self, 'id', 'new')}: {e}"
            )
            raise

    @validates(
        "min_quantity",
        "max_quantity",
        "batch_size",
        "expiration_days",
        "restock_delivery_days",
    )
    def validate_positive_integers(self, key: str, value: int | None) -> int | None:
        try:
            return validate_positive_integer(value, key, allow_none=True)
        except ValueError as e:
            logger.exception(
                f"Integer validation error for item {getattr(self, 'id', 'new')} field '{key}': {e}"
            )
            raise

    @validates("prior_daily_usage")
    def validate_prior_daily_usage(self, key: str, value: float | None) -> float | None:
        if value is None:
            return None
        try:
            value = float(value)
            if value < 0:
                raise ValueError("Prior daily usage must be non-negative")
            return value
        except (ValueError, TypeError) as e:
            logger.exception(
                f"Prior daily usage validation error for item {getattr(self, 'id', 'new')}: {e}"
            )
            raise ValueError("Prior daily usage must be a non-negative number")

    @validates("image")
    def validate_image(self, key: str, value: str | None) -> str | None:
        try:
            return validate_image_url(value)
        except ValueError as e:
            logger.exception(
                f"Image URL validation error for item {getattr(self, 'id', 'new')}: {e}"
            )
            raise

    @staticmethod
    def calculate_upc_check_digit(upc11: str) -> str:
        digits = [int(d) for d in upc11]
        odd_sum = sum(digits[::2]) * 3
        even_sum = sum(digits[1::2])
        total = odd_sum + even_sum
        return str((10 - total % 10) % 10)

    @staticmethod
    def generate_upc(db_session, user_id: int) -> str:
        """Generate a new UPC for a user using the provided session."""

        stmt = (
            select(Items)
            .where(Items.user_id == user_id)
            .where(Items.upc >= UPC_GENERATION_START)
            .order_by(Items.upc.desc())
        )
        largest_upc = db_session.execute(stmt).scalars().first()
        if largest_upc:
            base_11 = largest_upc.upc[:11]
            next_number = int(base_11) + 1
            next_base = str(next_number).zfill(11)
        else:
            next_base = UPC_GENERATION_START[:11]
        new_upc = next_base + Items.calculate_upc_check_digit(next_base)
        stmt_check = select(Items).where(Items.upc == new_upc)
        if db_session.execute(stmt_check).scalars().first():
            logger.error(
                f"UPC generation failure: Generated UPC {new_upc} already exists for user {user_id}"
            )
            raise ValueError("Generated UPC already exists")
        return new_upc

    @validates("upc")
    def validate_upc(self, key: str, value: str | None) -> str | None:
        if not value:
            return None
        if not isinstance(value, str):
            logger.error(
                f"UPC validation error for item {getattr(self, 'id', 'new')}: UPC must be a string, got {type(value)}"
            )
            raise ValueError("UPC must be a string.")
        if not value or value.strip() == "":
            return None
        if not value.isdigit() or len(value) != 12:
            logger.error(
                f"UPC validation error for item {getattr(self, 'id', 'new')}: Invalid UPC format '{value}' - must be 12 digits"
            )
            raise ValueError("UPC must be a 12-digit number.")
        calculated_check = self.calculate_upc_check_digit(value[:11])
        if calculated_check != value[11]:
            logger.error(
                f"UPC validation error for item {getattr(self, 'id', 'new')}: Invalid check digit for UPC '{value}'"
            )
            raise ValueError("Invalid UPC check digit.")
        # Enforce uniqueness when this instance is attached to a Session.
        # If there's no session or no user_id available yet, defer uniqueness
        # enforcement to higher-level application code.
        try:
            sess = object_session(self)
            user_id_val = getattr(self, "user_id", None)
            if sess is not None and user_id_val is not None:
                stmt = (
                    select(Items.id)
                    .where(Items.user_id == user_id_val)
                    .where(Items.upc == value)
                )
                if getattr(self, "id", None) is not None:
                    stmt = stmt.where(Items.id != self.id)
                existing = sess.execute(stmt).scalars().first()
                if existing:
                    logger.error(
                        f"UPC uniqueness validation error for item {getattr(self, 'id', 'new')}: UPC '{value}' already exists for user {user_id_val}"
                    )
                    raise ValueError("UPC must be unique per user.")
        except ValueError:
            # Re-raise validation errors as-is
            raise
        except SQLAlchemyError as db_error:
            # Log database errors but don't fail validation - uniqueness will be enforced at commit
            logger.warning(f"Database error during UPC uniqueness check: {db_error}")
            # Allow validation to continue - database constraint will catch duplicates
        return value


class ActionLogs(Base):
    __tablename__ = "action_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    item_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("items.id"))
    operation_type: Mapped[OperationType] = mapped_column(
        SAEnum(OperationType), nullable=False
    )
    from_location_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("user_item_locations.id")
    )
    to_location_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("user_item_locations.id")
    )

    quantity_delta: Mapped[int] = mapped_column(Integer, nullable=False)
    admin_action: Mapped[bool] = mapped_column(Boolean, default=False)
    time_scanned: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), nullable=False
    )

    item = relationship("Items", back_populates="action_logs", lazy="selectin")
    from_location = relationship(
        "UserItemLocations",
        foreign_keys=[from_location_id],
        backref="from_location_logs",
        lazy="selectin",
    )
    to_location = relationship(
        "UserItemLocations",
        foreign_keys=[to_location_id],
        backref="to_location_logs",
        lazy="selectin",
    )

    __table_args__ = (
        Index("idx_user_item_id", "user_id", "item_id"),
        Index("idx_user_from_location", "user_id", "from_location_id"),
        Index("idx_user_to_location", "user_id", "to_location_id"),
    )

    def __repr__(self) -> str:
        return f"<ActionLog {self.from_location} to {self.to_location}>"

    @validates("quantity_delta")
    def validate_quantity_delta(self, key: str, value: int | None) -> int | None:
        try:
            return validate_non_negative_integer(
                value, "quantity_delta", allow_none=False
            )
        except ValueError as e:
            logger.exception(
                f"Quantity delta validation error for action log {getattr(self, 'id', 'new')}: {e}"
            )
            raise

    @property
    def is_count(self) -> bool:
        return self.operation_type == OperationType.count

    @property
    def is_restock(self) -> bool:
        return self.operation_type == OperationType.restock

    @property
    def is_transfer(self) -> bool:
        return self.operation_type == OperationType.transfer

    @property
    def is_takeout(self) -> bool:
        return self.operation_type == OperationType.takeout

    def get_time_scanned_local(self, user_timezone: str) -> datetime:
        return convert_utc_to_local(self.time_scanned, user_timezone)

    def process_action(self, db_session) -> tuple[dict[int, int], list[Any]]:
        """Apply this action to computed quantities and detect alerts."""
        if self.item_id is None:
            logger.debug(
                "Skipping alert detection for ActionLog %s: no item_id", self.id
            )
            return {}, []

        exclude_ids = {self.id} if self.id else None
        previous_quantities = calculate_item_quantities(
            db_session,
            self.user_id,
            self.item_id,
            exclude_action_ids=exclude_ids,
        )
        updated_quantities = apply_action_to_quantities(previous_quantities, self)

        alerts: list[Any] = []

        try:
            from app.alerts.detection_service import (
                AlertDetectionService,  # Necessary inline import avoids circular dependency
            )

            result = AlertDetectionService.check_quantity_alerts(
                self.user_id,
                self.item_id,
                updated_quantities,
                previous_quantities,
                self.admin_action,
            )
            if result:
                alerts = result
        except Exception as e:
            logger.exception(f"Alert detection failed for ActionLog {self.id}: {e}")

        return updated_quantities, alerts


@event.listens_for(Items, "before_insert")
def generate_upc_before_insert(mapper, connection, target):
    """Listener reserved for lightweight tasks; UPC generation requiring DB queries
    should be performed in application code with an active session.
    """
    if not target.upc and getattr(target, "user_id", None):
        logger.debug("UPC auto-generation deferred to application-level code")
