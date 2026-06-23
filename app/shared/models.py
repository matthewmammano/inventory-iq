"""Shared infrastructure database models."""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.clock import utc_now_naive
from app.shared.database import Base


class SchedulerRun(Base):
    """One background job time window already claimed by the scheduler."""

    __tablename__ = "scheduler_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agency_id: Mapped[int] = mapped_column(Integer, default=0, index=True)
    job_name: Mapped[str] = mapped_column(String(80), index=True)
    period_key: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(20), default="started", index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "job_name",
            "agency_id",
            "period_key",
            name="uq_scheduler_runs_job_agency_period",
        ),
    )
