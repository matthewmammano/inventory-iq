"""SQLAlchemy ORM models for alert events and notification deliveries."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.clock import utc_now_naive
from app.shared.database import Base

from .constants import (
    AlertSeverity,
    AlertSourceType,
    AlertType,
    InventoryAlertEventStatus,
    NotificationDelivery,
    NotificationEmailStatus,
    NotificationKind,
)


class InventoryAlertEvent(Base):
    """Discrete non-stock alert fact that may be rendered into notification emails."""

    __tablename__ = "inventory_alert_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agency_id: Mapped[int] = mapped_column(Integer, ForeignKey("agencies.id"), index=True)
    alert_type: Mapped[AlertType] = mapped_column(SAEnum(AlertType, native_enum=False, length=32), index=True)
    severity: Mapped[AlertSeverity] = mapped_column(SAEnum(AlertSeverity, native_enum=False, length=16), index=True)
    status: Mapped[InventoryAlertEventStatus] = mapped_column(
        SAEnum(InventoryAlertEventStatus, native_enum=False, length=16),
        default=InventoryAlertEventStatus.PENDING,
        index=True,
    )
    source_type: Mapped[AlertSourceType] = mapped_column(SAEnum(AlertSourceType, native_enum=False, length=32), index=True)
    source_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    dedupe_key: Mapped[str] = mapped_column(String(255), index=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    event_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive, index=True)
    queued_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    notified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint("agency_id", "dedupe_key", name="uq_inventory_alert_events_agency_dedupe_key"),
        Index("idx_inventory_alert_events_agency_status_type", "agency_id", "status", "alert_type"),
    )

    def __repr__(self) -> str:
        return f"<InventoryAlertEvent {self.id}: {self.alert_type.value} {self.status.value}>"


class NotificationEmailDelivery(Base):
    """Rendered email delivery row for one notification recipient."""

    __tablename__ = "notification_email_deliveries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agency_id: Mapped[int] = mapped_column(Integer, ForeignKey("agencies.id"), index=True)
    agency_email_id: Mapped[int] = mapped_column(Integer, ForeignKey("agency_emails.id"), index=True)
    recipient_email_snapshot: Mapped[str] = mapped_column(String(255))
    notification_kind: Mapped[NotificationKind] = mapped_column(SAEnum(NotificationKind, native_enum=False, length=32), index=True)
    delivery: Mapped[NotificationDelivery] = mapped_column(SAEnum(NotificationDelivery, native_enum=False, length=16), index=True)
    status: Mapped[NotificationEmailStatus] = mapped_column(
        SAEnum(NotificationEmailStatus, native_enum=False, length=16),
        default=NotificationEmailStatus.PENDING,
        index=True,
    )
    send_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    dedupe_key: Mapped[str] = mapped_column(String(255), index=True)
    alert_event_ids_json: Mapped[list[int]] = mapped_column(JSON, default=list)
    subject: Mapped[str] = mapped_column(String(255))
    preview_text: Mapped[str] = mapped_column(String(255))
    body_html: Mapped[str] = mapped_column(Text)
    body_text: Mapped[str] = mapped_column(Text)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive, index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)

    __table_args__ = (
        UniqueConstraint("agency_id", "agency_email_id", "dedupe_key", name="uq_notification_email_deliveries_recipient_dedupe"),
        CheckConstraint("next_attempt_at IS NULL OR next_attempt_at >= send_at", name="ck_notification_email_next_attempt_after_send"),
        Index("idx_notification_email_deliveries_status_send", "status", "send_at"),
    )

    def __repr__(self) -> str:
        return f"<NotificationEmailDelivery {self.id}: {self.notification_kind.value} {self.delivery.value} {self.status.value}>"
