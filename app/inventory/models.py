"""SQLAlchemy ORM models for inventory domain."""

from datetime import date, datetime
from random import SystemRandom
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
    select,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates
from sqlalchemy.orm import Session as OrmSession

from app.shared.clock import utc_now_naive
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
    OperationType,
    UnknownUpcStatus,
)

_rng = SystemRandom()


class Item(Base):
    """Inventory item master record."""

    __tablename__ = "items"
    __allow_unmapped__ = True

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agency_id: Mapped[int] = mapped_column(Integer, ForeignKey("agencies.id"))
    name: Mapped[str] = mapped_column(String(100))
    upc: Mapped[str] = mapped_column(String(12), nullable=False)

    active: Mapped[bool] = mapped_column(Boolean, default=True)
    guest_quick_adjust: Mapped[bool] = mapped_column(Boolean, default=False)
    increments: Mapped[str | None] = mapped_column(String(50))
    tag_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    image: Mapped[str | None] = mapped_column(String(1024))
    expiration_tracking_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    expiration_notice_days_override: Mapped[int | None] = mapped_column(Integer, nullable=True)
    min_quantity: Mapped[int] = mapped_column(Integer)
    max_quantity: Mapped[int] = mapped_column(Integer)
    batch_size: Mapped[int | None] = mapped_column(Integer, default=1)
    restock_delivery_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prior_daily_usage: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_accessed: Mapped[datetime | None] = mapped_column(DateTime, default=utc_now_naive)

    action_logs = relationship("ActionLog", back_populates="item", lazy="select")
    secondary_upcs = relationship("ItemSecondaryUpc", back_populates="item", cascade="all, delete-orphan", lazy="select")
    tags: Any

    __table_args__ = (
        UniqueConstraint("agency_id", "upc", name="uq_items_agency_upc"),
        CheckConstraint(f"upc LIKE '{UPC_GENERATION_PREFIX}%'", name="ck_items_upc_private_prefix"),
        Index("idx_agency_name", "agency_id", "name"),
        Index("idx_agency_last_accessed", "agency_id", "last_accessed"),
        Index("idx_agency_upc", "agency_id", "upc"),
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

    @validates("upc")
    def validate_upc(self, _key: str, value: str | None) -> str:
        normalized = validate_upc_code(value)
        if not normalized.startswith(UPC_GENERATION_PREFIX):
            raise ValueError(f"Primary UPC must start with {UPC_GENERATION_PREFIX}")
        return normalized

    @validates("min_quantity", "max_quantity", "batch_size", "restock_delivery_days", "expiration_notice_days_override")
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


class ItemSecondaryUpc(Base):
    """Real package UPC alias linked to one inventory item."""

    __tablename__ = "item_secondary_upcs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agency_id: Mapped[int] = mapped_column(Integer, ForeignKey("agencies.id"), index=True)
    item_id: Mapped[int] = mapped_column(Integer, ForeignKey("items.id", ondelete="CASCADE"), index=True)
    upc: Mapped[str] = mapped_column(String(12))
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    item = relationship("Item", back_populates="secondary_upcs", lazy="select")

    __table_args__ = (
        UniqueConstraint("agency_id", "upc", name="uq_item_secondary_upcs_agency_upc"),
        CheckConstraint(f"upc NOT LIKE '{UPC_GENERATION_PREFIX}%'", name="ck_item_secondary_upcs_not_private_prefix"),
        Index("idx_item_secondary_upcs_agency_item", "agency_id", "item_id"),
        Index("idx_item_secondary_upcs_agency_upc", "agency_id", "upc"),
    )

    @validates("upc")
    def validate_upc(self, _key: str, value: str | None) -> str:
        normalized = validate_upc_code(value)
        if normalized.startswith(UPC_GENERATION_PREFIX):
            raise ValueError(f"Secondary UPC cannot start with {UPC_GENERATION_PREFIX}")
        return normalized


class UnknownUpcScan(Base):
    """Unknown UPC waiting for admin review."""

    __tablename__ = "unknown_upc_scans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agency_id: Mapped[int] = mapped_column(Integer, ForeignKey("agencies.id"), index=True)
    upc: Mapped[str] = mapped_column(String(12))
    status: Mapped[UnknownUpcStatus] = mapped_column(SAEnum(UnknownUpcStatus), default=UnknownUpcStatus.PENDING, index=True)
    suggested_item_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("items.id"), nullable=True)
    lookup_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive, onupdate=utc_now_naive)

    suggested_item = relationship("Item", lazy="selectin")

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


@event.listens_for(OrmSession, "before_flush")
def _fill_primary_upcs(session: OrmSession, *_args) -> None:
    reserved = {item.upc for item in session.new if isinstance(item, Item) and item.upc}
    for item in session.new:
        if isinstance(item, Item) and not item.upc and item.agency_id:
            item.upc = _generate_primary_upc(session, item.agency_id, reserved)
            reserved.add(item.upc)


def _generate_primary_upc(session: OrmSession, agency_id: int, reserved: set[str]) -> str:
    for _ in range(100):
        body = f"{UPC_GENERATION_PREFIX}{_rng.randrange(10**8):08d}"
        upc = body + _upc_check_digit(body)
        if upc not in reserved and not agency_upc_exists(session, agency_id, upc):
            return upc
    raise ValueError("Could not generate a unique primary UPC.")


def agency_upc_exists(session: OrmSession, agency_id: int, upc: str) -> bool:
    return (
        session.scalar(select(Item.id).where(Item.agency_id == agency_id, Item.upc == upc)) is not None
        or session.scalar(
            select(ItemSecondaryUpc.id).where(
                ItemSecondaryUpc.agency_id == agency_id,
                ItemSecondaryUpc.upc == upc,
                ItemSecondaryUpc.active.is_(True),
            )
        )
        is not None
    )


class ActionLog(Base):
    """Inventory action log."""

    __tablename__ = "action_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agency_id: Mapped[int] = mapped_column(Integer, ForeignKey("agencies.id"))
    item_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("items.id"))
    operation_type: Mapped[OperationType] = mapped_column(SAEnum(OperationType))
    quantity: Mapped[int] = mapped_column(Integer)
    from_storage_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("agency_storages.id"))
    to_storage_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("agency_storages.id"))
    admin_action: Mapped[bool] = mapped_column(Boolean)
    time_scanned: Mapped[datetime | None] = mapped_column(DateTime, default=utc_now_naive, nullable=False)

    item = relationship("Item", back_populates="action_logs", lazy="select")
    from_storage = relationship("Storage", foreign_keys=[from_storage_id], lazy="select")
    to_storage = relationship("Storage", foreign_keys=[to_storage_id], lazy="select")
    expiration_lines = relationship("ActionLogExpirationLine", back_populates="action_log", cascade="all, delete-orphan", lazy="select")

    __table_args__ = (
        Index("idx_agency_item_id", "agency_id", "item_id"),
        Index("idx_agency_from_location", "agency_id", "from_storage_id"),
        Index("idx_agency_to_location", "agency_id", "to_storage_id"),
        Index("idx_action_logs_agency_item_time_id", "agency_id", "item_id", "time_scanned", "id"),
        Index("idx_action_logs_agency_to_operation_time_id", "agency_id", "to_storage_id", "operation_type", "time_scanned", "id"),
        Index("idx_action_logs_agency_from_operation_time_id", "agency_id", "from_storage_id", "operation_type", "time_scanned", "id"),
        Index("idx_action_logs_agency_id_desc", "agency_id", "id"),
    )

    @validates("quantity")
    def validate_quantity(self, _key: str, value: int | None) -> int | None:
        return validate_non_negative_integer(value, "quantity", allow_none=False)

    @property
    def is_count(self) -> bool:
        return self.operation_type.is_count

    @property
    def is_restock(self) -> bool:
        return self.operation_type.is_restock

    @property
    def is_transfer(self) -> bool:
        return self.operation_type.is_transfer

    @property
    def is_takeout(self) -> bool:
        return self.operation_type.is_takeout

    @property
    def expiration_summary(self) -> str:
        if not self.expiration_lines:
            return ""
        lines = sorted(self.expiration_lines, key=lambda line: (line.expires_on is None, line.expires_on or date.max))
        return ", ".join(f"{line.expires_on.isoformat() if line.expires_on else 'Other'} x{line.quantity}" for line in lines if line.quantity)

    def get_time_scanned_local(self, user_timezone: str) -> datetime | None:
        """Return time_scanned converted from UTC to the user's local timezone."""
        return convert_utc_to_local(self.time_scanned, user_timezone)


class InventoryStorageBalance(Base):
    """Current per-item, per-storage quantity derived from action history."""

    __tablename__ = "inventory_storage_balances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agency_id: Mapped[int] = mapped_column(Integer, ForeignKey("agencies.id"))
    item_id: Mapped[int] = mapped_column(Integer, ForeignKey("items.id"))
    storage_id: Mapped[int] = mapped_column(Integer, ForeignKey("agency_storages.id"))
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    last_counted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_takeout_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive, nullable=False)

    item = relationship("Item", lazy="selectin")
    storage = relationship("Storage", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("agency_id", "item_id", "storage_id", name="uq_inventory_storage_balances_agency_item_storage"),
        Index("idx_inventory_storage_balances_agency_storage", "agency_id", "storage_id"),
        Index("idx_inventory_storage_balances_agency_item", "agency_id", "item_id"),
    )

    @validates("quantity")
    def validate_quantity(self, _key: str, value: int | None) -> int:
        if value is None:
            raise ValueError("quantity cannot be None")
        return int(value)


class InventoryExpirationBalance(Base):
    """Current per-item, per-storage, per-expiration-date quantity."""

    __tablename__ = "inventory_expiration_balances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agency_id: Mapped[int] = mapped_column(Integer, ForeignKey("agencies.id"))
    item_id: Mapped[int] = mapped_column(Integer, ForeignKey("items.id"))
    storage_id: Mapped[int] = mapped_column(Integer, ForeignKey("agency_storages.id"))
    expires_on: Mapped[date] = mapped_column(Date)
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    last_counted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive, nullable=False)

    item = relationship("Item", lazy="selectin")
    storage = relationship("Storage", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("agency_id", "item_id", "storage_id", "expires_on", name="uq_inventory_expiration_balances_key"),
        Index("idx_inventory_expiration_balances_agency_item_storage", "agency_id", "item_id", "storage_id"),
        Index("idx_inventory_expiration_balances_agency_expires", "agency_id", "expires_on"),
    )

    @validates("quantity")
    def validate_quantity(self, _key: str, value: int | None) -> int:
        if value is None:
            raise ValueError("quantity cannot be None")
        return int(value)


class ActionLogExpirationLine(Base):
    """Expiration-date allocation attached to one inventory action."""

    __tablename__ = "action_log_expiration_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    action_log_id: Mapped[int] = mapped_column(Integer, ForeignKey("action_logs.id", ondelete="CASCADE"), index=True)
    expires_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    quantity: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive, nullable=False)

    action_log = relationship("ActionLog", back_populates="expiration_lines", lazy="selectin")

    @validates("quantity")
    def validate_quantity(self, _key: str, value: int | None) -> int | None:
        return validate_non_negative_integer(value, "quantity", allow_none=False)


class InventoryItemLocationState(Base):
    """Current per-item, per-location rollup, trend, forecast, and stock alert state."""

    __tablename__ = "inventory_item_location_states"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agency_id: Mapped[int] = mapped_column(Integer, ForeignKey("agencies.id"), index=True)
    item_id: Mapped[int] = mapped_column(Integer, ForeignKey("items.id"), index=True)
    agency_location_id: Mapped[int] = mapped_column(Integer, ForeignKey("agency_locations.id"), index=True)

    total_quantity: Mapped[int] = mapped_column(Integer, default=0)
    min_quantity_snapshot: Mapped[int] = mapped_column(Integer, default=0)
    lead_time_days_snapshot: Mapped[int] = mapped_column(Integer, default=0)
    restock_delivery_days_snapshot: Mapped[int | None] = mapped_column(Integer, nullable=True)

    last_counted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_takeout_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    trend_per_day: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    segment_count: Mapped[int] = mapped_column(Integer, default=0)
    data_signature: Mapped[str | None] = mapped_column(String(64), nullable=True)
    trained_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    days_until_low: Mapped[float | None] = mapped_column(Float, nullable=True)
    days_until_stockout: Mapped[float | None] = mapped_column(Float, nullable=True)

    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    state_version_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "agency_id",
            "item_id",
            "agency_location_id",
            name="uq_inventory_item_location_states_agency_item_location",
        ),
        Index("idx_inventory_item_location_states_signature", "data_signature"),
    )

    @validates("total_quantity", "min_quantity_snapshot", "lead_time_days_snapshot")
    def validate_state_integer(self, _key: str, value: int | None) -> int:
        if value is None:
            return 0
        return int(value)
