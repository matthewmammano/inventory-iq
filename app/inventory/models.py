"""SQLAlchemy ORM models for inventory domain."""

from datetime import datetime
from typing import Any

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
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

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
    OperationType,
    UnknownUpcStatus,
)


class Items(Base):
    """Inventory item master record."""

    __tablename__ = "items"
    __allow_unmapped__ = True

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
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
    upc_codes = relationship("ItemUpcCode", back_populates="item", cascade="all, delete-orphan", lazy="selectin")
    tags: Any

    __table_args__ = (
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


class ItemUpcCode(Base):
    """Valid UPC code linked to one inventory item."""

    __tablename__ = "item_upc_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agency_id: Mapped[int] = mapped_column(Integer, ForeignKey("agencies.id"), index=True)
    item_id: Mapped[int] = mapped_column(Integer, ForeignKey("items.id", ondelete="CASCADE"), index=True)
    upc: Mapped[str] = mapped_column(String(12))

    item = relationship("Items", back_populates="upc_codes", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("agency_id", "upc", name="uq_item_upc_codes_agency_upc"),
        Index("idx_item_upc_codes_agency_item", "agency_id", "item_id"),
        Index("idx_item_upc_codes_agency_upc", "agency_id", "upc"),
    )

    @validates("upc")
    def validate_upc(self, _key: str, value: str | None) -> str:
        return validate_upc_code(value)


class UnknownUpcScan(Base):
    """Unknown UPC waiting for admin review."""

    __tablename__ = "unknown_upc_scans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agency_id: Mapped[int] = mapped_column(Integer, ForeignKey("agencies.id"), index=True)
    upc: Mapped[str] = mapped_column(String(12))
    lookup_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    suggested_item_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("items.id"), nullable=True)
    status: Mapped[UnknownUpcStatus] = mapped_column(SAEnum(UnknownUpcStatus), default=UnknownUpcStatus.PENDING, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)

    suggested_item = relationship("Items", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("agency_id", "upc", name="uq_unknown_upc_scans_agency_upc"),
        Index("idx_unknown_upc_scans_agency_status_created", "agency_id", "status", "created_at"),
    )

    @validates("upc")
    def validate_upc(self, _key: str, value: str | None) -> str:
        return validate_upc_code(value)


def validate_upc_code(value: str | None) -> str:
    if not value or not isinstance(value, str):
        raise ValueError("UPC must be a string")
    normalized = value.strip()
    if not normalized.isdigit() or len(normalized) != 12:
        raise ValueError("UPC must be a 12-digit number")
    if _upc_check_digit(normalized[:11]) != normalized[11]:
        raise ValueError("Invalid UPC check digit")
    return normalized


def _upc_check_digit(upc11: str) -> str:
    digits = [int(digit) for digit in upc11]
    total = sum(digits[::2]) * 3 + sum(digits[1::2])
    return str((10 - total % 10) % 10)


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
