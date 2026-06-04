"""Persisted prediction parameters."""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.clock import utc_now
from app.shared.database import Base


class InventoryTrend(Base):
    """Learned location-level trend for one agency item."""

    __tablename__ = "inventory_trends"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agency_id: Mapped[int] = mapped_column(Integer, ForeignKey("agencies.id"), index=True)
    item_id: Mapped[int] = mapped_column(Integer, ForeignKey("items.id"), index=True)
    agency_location_id: Mapped[int] = mapped_column(Integer, ForeignKey("agency_locations.id"), index=True)
    trend_per_day: Mapped[float] = mapped_column(Float)
    confidence_percent: Mapped[float | None] = mapped_column(Float)
    segment_count: Mapped[int] = mapped_column(Integer, default=0)
    data_signature: Mapped[str] = mapped_column(String(64))
    trained_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    __table_args__ = (
        UniqueConstraint(
            "agency_id",
            "item_id",
            "agency_location_id",
            name="uq_inventory_trends_agency_item_location",
        ),
        Index("idx_inventory_trends_signature", "data_signature"),
    )
