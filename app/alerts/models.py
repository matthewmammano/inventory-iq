"""SQLAlchemy ORM models for alerts."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.shared.clock import utc_now_naive
from app.shared.database import Base

from .constants import AlertAction, AlertType


class AlertRecords(Base):
    """Minimal alert state; email rows are built from details_json at send time."""

    __tablename__ = "alert_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agency_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("agencies.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[AlertType] = mapped_column(SAEnum(AlertType), index=True)
    action: Mapped[AlertAction] = mapped_column(
        SAEnum(AlertAction), default=AlertAction.PENDING, index=True
    )
    scheduled: Mapped[datetime] = mapped_column(DateTime, index=True)
    details_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive, index=True)
    action_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utc_now_naive,
        onupdate=utc_now_naive,
    )

    agency = relationship("Agencies", back_populates="alert_records")

    def __repr__(self) -> str:
        return f"<AlertRecord {self.id}: {self.type.value} {self.action.value}>"
