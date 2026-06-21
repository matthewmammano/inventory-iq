"""SQLAlchemy ORM models for inventory domain."""

from datetime import datetime
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
    UniqueConstraint,
    event,
    update,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Mapped, mapped_column, object_session, relationship, validates
from sqlalchemy.orm.attributes import set_committed_value

from app.shared.clock import utc_now
from app.shared.database import Base
from app.shared.timezone_utils import convert_utc_to_local
from app.shared.validators import (
    validate_image_url,
    validate_non_negative_integer,
    validate_positive_integer,
    validate_string_length,
)

from .constants import (
    UPC_GENERATION_PREFIX,
    UPC_PAYLOAD_LENGTH,
    OperationType,
)


class Items(Base):
    """Inventory item master record."""

    __tablename__ = "items"
    __allow_unmapped__ = True

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    upc: Mapped[str | None] = mapped_column(String(12))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    guest_quick_adjust: Mapped[bool] = mapped_column(Boolean, default=False)

    agency_id: Mapped[int] = mapped_column(Integer, ForeignKey("agencies.id"))
    tag_ids: Mapped[list[int]] = mapped_column(JSON, default=list)

    increments: Mapped[str | None] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(100))
    image: Mapped[str | None] = mapped_column(String(1024))
    last_accessed: Mapped[datetime | None] = mapped_column(DateTime, default=utc_now)

    min_quantity: Mapped[int] = mapped_column(Integer)
    max_quantity: Mapped[int] = mapped_column(Integer)
    batch_size: Mapped[int | None] = mapped_column(Integer, default=1)
    restock_delivery_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prior_daily_usage: Mapped[float] = mapped_column(Float)

    action_logs = relationship("ActionLogs", back_populates="item", lazy="selectin")
    tags: Any

    __table_args__ = (
        UniqueConstraint("agency_id", "upc", name="uq_items_agency_upc"),
        Index("idx_agency_upc", "agency_id", "upc"),
        Index("idx_agency_name", "agency_id", "name"),
        Index("idx_agency_last_accessed", "agency_id", "last_accessed"),
    )

    def __repr__(self) -> str:
        return f"<Item {self.name}>"

    def get_last_accessed_local(self, user_timezone: str) -> datetime | None:
        """Return last_accessed converted from UTC to the user's local timezone."""
        return convert_utc_to_local(self.last_accessed, user_timezone)

    def add_tag(self, tag_id: int) -> None:
        if not isinstance(tag_id, int):
            raise ValueError("Tag ID must be an integer")
        if self.tag_ids is None:
            self.tag_ids = []
        if tag_id not in self.tag_ids:
            self.tag_ids.append(tag_id)

    def remove_tag(self, tag_id: int) -> None:
        if not isinstance(tag_id, int):
            raise ValueError("Tag ID must be an integer")
        if self.tag_ids and tag_id in self.tag_ids:
            self.tag_ids.remove(tag_id)

    @validates("tag_ids")
    def validate_tag_ids(self, _key: str, value: list[int]) -> list[int]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("tag_ids must be a list")
        for tag_id in value:
            if not isinstance(tag_id, int):
                raise ValueError("Tag ID must be an integer")
        return value

    @validates("name")
    def validate_name(self, _key: str, value: str | None) -> str | None:
        return validate_string_length(value, "name", 100, allow_none=False, allow_empty=False)

    @validates("increments")
    def validate_increments(self, _key: str, value: str | None) -> str | None:
        return validate_string_length(value, "increments", 50, allow_none=True, allow_empty=True)

    @validates("min_quantity", "max_quantity", "batch_size", "restock_delivery_days")
    def validate_positive_integers(self, key: str, value: int | None) -> int | None:
        return validate_positive_integer(value, key, allow_none=True)

    @validates("prior_daily_usage")
    def validate_prior_daily_usage(self, _key: str, value: float | None) -> float | None:
        if value is None:
            return None
        value = float(value)
        if value < 0:
            raise ValueError("Prior daily usage must be non-negative")
        return value

    @validates("image")
    def validate_image(self, _key: str, value: str | None) -> str | None:
        return validate_image_url(value)

    @staticmethod
    def calculate_upc_check_digit(upc11: str) -> str:
        digits = [int(d) for d in upc11]
        odd_sum = sum(digits[::2]) * 3
        even_sum = sum(digits[1::2])
        total = odd_sum + even_sum
        return str((10 - total % 10) % 10)

    @staticmethod
    def generated_upc_from_id(item_id: int) -> str:
        base = f"{UPC_GENERATION_PREFIX}{item_id:0>{UPC_PAYLOAD_LENGTH - 1}}"
        return base + Items.calculate_upc_check_digit(base)

    @validates("upc")
    def validate_upc(self, _key: str, value: str | None) -> str | None:
        if not value:
            return None
        if not isinstance(value, str):
            raise ValueError("UPC must be a string")
        if not value.isdigit() or len(value) != 12:
            raise ValueError("UPC must be a 12-digit number")
        calculated_check = self.calculate_upc_check_digit(value[:11])
        if calculated_check != value[11]:
            raise ValueError("Invalid UPC check digit")
        try:
            sess = object_session(self)
            agency_id_val = getattr(self, "agency_id", None)
            if sess is not None and agency_id_val is not None:
                stmt = sess.query(Items.id).filter(Items.agency_id == agency_id_val).filter(Items.upc == value)
                if getattr(self, "id", None) is not None:
                    stmt = stmt.filter(Items.id != self.id)
                existing = stmt.first()
                if existing:
                    raise ValueError("UPC must be unique per agency")
        except SQLAlchemyError as db_error:
            logger.warning(f"UPC uniqueness check skipped because the database lookup failed: {db_error}")
        return value


class ActionLogs(Base):
    """Inventory action log."""

    __tablename__ = "action_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agency_id: Mapped[int] = mapped_column(Integer, ForeignKey("agencies.id"))
    item_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("items.id"))
    operation_type: Mapped[OperationType] = mapped_column(SAEnum(OperationType))
    from_location_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("agency_storages.id"))
    to_location_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("agency_storages.id"))

    quantity_delta: Mapped[int] = mapped_column(Integer)
    admin_action: Mapped[bool] = mapped_column(Boolean)
    time_scanned: Mapped[datetime | None] = mapped_column(DateTime, default=utc_now, nullable=False)

    item = relationship("Items", back_populates="action_logs", lazy="selectin")
    from_location = relationship("AgencyStorages", foreign_keys=[from_location_id], lazy="selectin")
    to_location = relationship("AgencyStorages", foreign_keys=[to_location_id], lazy="selectin")

    __table_args__ = (
        Index("idx_agency_item_id", "agency_id", "item_id"),
        Index("idx_agency_from_location", "agency_id", "from_location_id"),
        Index("idx_agency_to_location", "agency_id", "to_location_id"),
        Index("idx_action_logs_agency_item_time_id", "agency_id", "item_id", "time_scanned", "id"),
        Index("idx_action_logs_agency_to_operation_time_id", "agency_id", "to_location_id", "operation_type", "time_scanned", "id"),
        Index("idx_action_logs_agency_from_operation_time_id", "agency_id", "from_location_id", "operation_type", "time_scanned", "id"),
        Index("idx_action_logs_agency_id_desc", "agency_id", "id"),
    )

    @validates("quantity_delta")
    def validate_quantity_delta(self, _key: str, value: int | None) -> int | None:
        return validate_non_negative_integer(value, "quantity_delta", allow_none=False)

    @property
    def is_count(self) -> bool:
        return self.operation_type == OperationType.COUNT

    @property
    def is_restock(self) -> bool:
        return self.operation_type == OperationType.RESTOCK

    @property
    def is_transfer(self) -> bool:
        return self.operation_type == OperationType.TRANSFER

    @property
    def is_takeout(self) -> bool:
        return self.operation_type == OperationType.TAKEOUT

    def get_time_scanned_local(self, user_timezone: str) -> datetime | None:
        """Return time_scanned converted from UTC to the user's local timezone."""
        return convert_utc_to_local(self.time_scanned, user_timezone)


class InventoryBalances(Base):
    """Current per-item, per-storage quantity derived from action history."""

    __tablename__ = "inventory_balances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agency_id: Mapped[int] = mapped_column(Integer, ForeignKey("agencies.id"))
    item_id: Mapped[int] = mapped_column(Integer, ForeignKey("items.id"))
    storage_id: Mapped[int] = mapped_column(Integer, ForeignKey("agency_storages.id"))
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    last_counted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_takeout_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)

    item = relationship("Items", lazy="selectin")
    storage = relationship("AgencyStorages", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("agency_id", "item_id", "storage_id", name="uq_inventory_balances_agency_item_storage"),
        Index("idx_inventory_balances_agency_storage", "agency_id", "storage_id"),
        Index("idx_inventory_balances_agency_item", "agency_id", "item_id"),
    )

    @validates("quantity")
    def validate_quantity(self, _key: str, value: int | None) -> int:
        if value is None:
            raise ValueError("quantity cannot be None")
        return int(value)


@event.listens_for(Items, "after_insert")
def auto_assign_generated_upc(_mapper, connection, item: Items) -> None:
    if item.upc or item.id is None:
        return
    upc = Items.generated_upc_from_id(item.id)
    connection.execute(update(Items).where(Items.id == item.id).values(upc=upc))
    set_committed_value(item, "upc", upc)
