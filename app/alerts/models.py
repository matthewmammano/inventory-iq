"""SQLAlchemy ORM models: alerts, per-recipient notifications, and email audit."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.clock import utc_now_naive
from app.shared.database import Base

from .constants import AlertStatus, AlertType, ClosedReason, DeliveryStatus, NotificationDeliveryKind


class Alert(Base):
    """One notifiable problem: a stock condition or a discrete event.

    Created the moment a scan or audit detects it. Any real change (worsening,
    resolving, or recurring after resolution) closes the current row and opens a
    fresh one, so a new occurrence always starts with a clean notification slate.
    Severity is never stored; it is derived from `alert_type`.
    """

    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agency_id: Mapped[int] = mapped_column(Integer, ForeignKey("agencies.id"), index=True)
    alert_type: Mapped[AlertType] = mapped_column(SAEnum(AlertType, native_enum=False, length=32), index=True)
    item_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("items.id"), nullable=True, index=True)
    agency_location_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("agency_locations.id"), nullable=True, index=True)
    status: Mapped[AlertStatus] = mapped_column(SAEnum(AlertStatus, native_enum=False, length=16), default=AlertStatus.OPEN, index=True)
    closed_reason: Mapped[ClosedReason | None] = mapped_column(SAEnum(ClosedReason, native_enum=False, length=16), nullable=True)
    dedupe_key: Mapped[str] = mapped_column(String(255), index=True)
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    opened_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive, index=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_alerts_agency_status_type", "agency_id", "status", "alert_type"),
        Index(
            "uq_alerts_open_dedupe_key",
            "agency_id",
            "dedupe_key",
            unique=True,
            postgresql_where=text("status = 'OPEN'"),
            sqlite_where=text("status = 'OPEN'"),
        ),
    )

    @property
    def severity(self) -> Any:
        return self.alert_type.severity

    def __repr__(self) -> str:
        return f"<Alert {self.id}: {self.alert_type.value} {self.status.value}>"


class AlertNotification(Base):
    """Append-only record that one recipient was emailed about one alert.

    The absence of a row for a (recipient, alert) pair is what makes a recipient
    due; a recurring problem gets a brand-new `alert_id`, so it is always due.
    """

    __tablename__ = "alert_notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    alert_id: Mapped[int] = mapped_column(Integer, ForeignKey("alerts.id"), index=True)
    notification_recipient_id: Mapped[int] = mapped_column(Integer, ForeignKey("notification_recipients.id"), index=True)
    email_delivery_id: Mapped[int] = mapped_column(Integer, ForeignKey("email_deliveries.id"), index=True)
    notified_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)

    __table_args__ = (Index("idx_alert_notifications_recipient_alert", "notification_recipient_id", "alert_id", "notified_at"),)

    def __repr__(self) -> str:
        return f"<AlertNotification recipient={self.notification_recipient_id} alert={self.alert_id}>"


class EmailDelivery(Base):
    """Write-once audit of one notification email send attempt.

    Records what went out (subject/preview) or why it failed, never the body,
    never a queue. Eligibility is decided fresh each run from alerts + the ledger.
    """

    __tablename__ = "email_deliveries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agency_id: Mapped[int] = mapped_column(Integer, ForeignKey("agencies.id"), index=True)
    notification_recipient_id: Mapped[int] = mapped_column(Integer, ForeignKey("notification_recipients.id"), index=True)
    recipient_email_snapshot: Mapped[str] = mapped_column(String(255))
    kind: Mapped[NotificationDeliveryKind] = mapped_column(SAEnum(NotificationDeliveryKind, native_enum=False, length=16), index=True)
    status: Mapped[DeliveryStatus] = mapped_column(SAEnum(DeliveryStatus, native_enum=False, length=16), index=True)
    subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    preview_text: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive, index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)

    __table_args__ = (Index("idx_email_deliveries_recipient_kind_sent", "notification_recipient_id", "kind", "sent_at"),)

    def __repr__(self) -> str:
        return f"<EmailDelivery {self.id}: {self.kind.value} {self.status.value}>"
