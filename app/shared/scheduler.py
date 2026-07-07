"""Small in-process scheduler for demo/runtime jobs."""

import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from zoneinfo import ZoneInfo

from flask import Flask
from loguru import logger
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.alerts.alert_service import generate_scheduled_alerts
from app.alerts.email_service import process_all_alerts
from app.auth.models import Agency
from app.inventory.balance_service import BalanceReconciliationResult, reconcile_inventory_balances
from app.shared.clock import current_speed, utc_now
from app.shared.config import settings
from app.shared.database import get_session
from app.shared.models import SchedulerRun

GLOBAL_SCHEDULER_AGENCY_ID = 0


class SchedulerJobName(StrEnum):
    PROCESS_ALERT_EMAILS = "PROCESS_ALERT_EMAILS"
    GENERATE_INVENTORY_ALERTS = "GENERATE_INVENTORY_ALERTS"
    RECONCILE_INVENTORY_BALANCES = "RECONCILE_INVENTORY_BALANCES"
    RETRAIN_MODELS = "RETRAIN_MODELS"


class SchedulerRunStatus(StrEnum):
    STARTED = "STARTED"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class DailySchedulerSpec:
    job_name: SchedulerJobName
    local_hour: int
    local_minute: int

    @property
    def local_time_label(self) -> str:
        return f"{self.local_hour:02d}:{self.local_minute:02d}"

    def period_key(self, now: datetime, timezone: str) -> str | None:
        local_now = now.astimezone(ZoneInfo(timezone))
        if (local_now.hour, local_now.minute) < (self.local_hour, self.local_minute):
            return None
        return local_now.strftime("%Y-%m-%d")


EMAIL_DELIVERY_PERIOD_MINUTES = 10
INVENTORY_AUDIT_SCHEDULE = DailySchedulerSpec(SchedulerJobName.GENERATE_INVENTORY_ALERTS, 7, 46)
BALANCE_AUDIT_SCHEDULE = DailySchedulerSpec(SchedulerJobName.RECONCILE_INVENTORY_BALANCES, 4, 17)

_started = False


def start_scheduler(app: Flask) -> None:
    """Start background jobs when explicitly enabled."""
    global _started
    if _started or not settings.scheduler_enabled:
        return
    if settings.is_prod:
        logger.warning("In-process scheduler disabled in prod; use Railway cron")
        return

    _started = True
    thread = threading.Thread(target=_run_loop, args=(app,), daemon=True)
    thread.start()
    logger.info(
        "Development scheduler started",
        extra={"poll_seconds": settings.scheduler_poll_seconds},
    )


def _run_loop(app: Flask) -> None:
    while True:
        try:
            with app.app_context():
                _run_due_jobs()
        except Exception:
            logger.exception("Scheduler loop failed while running due jobs")
        time.sleep(_poll_seconds())


def _run_due_jobs() -> None:
    now = utc_now()
    _run_daily_inventory_job(now)
    _run_daily_balance_job(now)
    _run_email_delivery_job(now)


def _run_email_delivery_job(now: datetime) -> None:
    period_key = _email_delivery_period_key(now)
    with claimed_scheduler_run(SchedulerJobName.PROCESS_ALERT_EMAILS, period_key) as run_id:
        if run_id is None:
            return
        result = process_all_alerts()
    logger.info("Scheduled notification email job finished", extra=result | {"period_key": period_key})


def _run_daily_inventory_job(now: datetime) -> None:
    total = 0
    for agency_id, timezone in _active_agency_schedules():
        period_key = INVENTORY_AUDIT_SCHEDULE.period_key(now, timezone)
        if period_key is None:
            continue

        try:
            with claimed_scheduler_run(INVENTORY_AUDIT_SCHEDULE.job_name, period_key, agency_id) as run_id:
                if run_id is None:
                    continue
                total += _generate_agency_inventory_alerts(agency_id)
        except Exception:
            logger.exception(
                "Scheduled inventory alert audit failed",
                extra={"agency_id": agency_id, "period_key": period_key},
            )
    if total:
        logger.info("Scheduled inventory alert audit finished", extra={"rows_checked": total})


def _run_daily_balance_job(now: datetime) -> None:
    ran = False
    total_mismatches = 0
    total_repaired_rows = 0
    for agency_id, timezone in _active_agency_schedules():
        period_key = BALANCE_AUDIT_SCHEDULE.period_key(now, timezone)
        if period_key is None:
            continue

        try:
            with claimed_scheduler_run(BALANCE_AUDIT_SCHEDULE.job_name, period_key, agency_id) as run_id:
                if run_id is None:
                    continue
                ran = True
                result = _reconcile_agency_inventory_balances(agency_id)
                total_mismatches += result.mismatch_count
                total_repaired_rows += result.repaired_row_count
        except Exception:
            logger.exception(
                "Scheduled inventory balance audit failed",
                extra={"agency_id": agency_id, "period_key": period_key},
            )
    if not ran:
        return
    logger.info(
        "Scheduled inventory balance audit finished",
        extra={
            "job_name": BALANCE_AUDIT_SCHEDULE.job_name.value,
            "schedule_local_time": BALANCE_AUDIT_SCHEDULE.local_time_label,
            "mismatch_count": total_mismatches,
            "repaired_row_count": total_repaired_rows,
        },
    )


def _active_agency_schedules() -> list[tuple[int, str]]:
    with get_session() as session:
        rows = session.execute(select(Agency.id, Agency.timezone).where(Agency.active.is_(True))).all()
        return [(agency_id, timezone or "UTC") for agency_id, timezone in rows]


def _email_delivery_period_key(now: datetime) -> str:
    minute = now.minute - (now.minute % EMAIL_DELIVERY_PERIOD_MINUTES)
    return now.replace(minute=minute, second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M")


def scheduler_daily_period_key(now: datetime | None = None) -> str:
    current = now or utc_now()
    return current.strftime("%Y-%m-%d")


def scheduler_email_period_key(now: datetime | None = None) -> str:
    return _email_delivery_period_key(now or utc_now())


def _generate_agency_inventory_alerts(agency_id: int) -> int:
    with get_session() as session:
        count = generate_scheduled_alerts(session, agency_id)
        session.commit()
        return count


def run_inventory_balance_audit(
    agency_id: int | None = None,
    *,
    repair: bool = True,
) -> dict[str, int | str]:
    """Run the balance audit immediately for one agency or all active agencies."""
    agency_ids = [agency_id] if agency_id is not None else [agency_id for agency_id, _ in _active_agency_schedules()]
    agencies_checked = 0
    mismatch_count = 0
    repaired_row_count = 0
    for current_agency_id in agency_ids:
        result = _reconcile_agency_inventory_balances(current_agency_id, repair=repair)
        agencies_checked += 1
        mismatch_count += result.mismatch_count
        repaired_row_count += result.repaired_row_count

    summary: dict[str, int | str] = {
        "job_name": SchedulerJobName.RECONCILE_INVENTORY_BALANCES.value,
        "agencies_checked": agencies_checked,
        "mismatch_count": mismatch_count,
        "repaired_row_count": repaired_row_count,
    }
    logger.info("Inventory balance audit run finished", extra=summary | {"repair": repair})
    return summary


def _reconcile_agency_inventory_balances(
    agency_id: int,
    *,
    repair: bool = True,
) -> BalanceReconciliationResult:
    with get_session() as session:
        result = reconcile_inventory_balances(session, agency_id, repair=repair)
        session.commit()
        return result


def claim_scheduler_run(
    job_name: SchedulerJobName,
    period_key: str,
    agency_id: int = GLOBAL_SCHEDULER_AGENCY_ID,
) -> int | None:
    with get_session() as session:
        existing_id = session.scalar(
            select(SchedulerRun.id).where(
                SchedulerRun.job_name == job_name.value,
                SchedulerRun.agency_id == agency_id,
                SchedulerRun.period_key == period_key,
            )
        )
        if existing_id is not None:
            return None

        run = SchedulerRun(
            job_name=job_name.value,
            agency_id=agency_id,
            period_key=period_key,
            status=SchedulerRunStatus.STARTED.value,
        )
        session.add(run)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            return None
        return run.id


def finish_scheduler_run(run_id: int, status: SchedulerRunStatus, error: str | None = None) -> None:
    with get_session() as session:
        run = session.get(SchedulerRun, run_id)
        if run is None:
            logger.warning("Scheduler run marker missing", extra={"scheduler_run_id": run_id})
            return
        run.status = status.value
        run.finished_at = utc_now().replace(tzinfo=None)
        run.error = error[:1000] if error else None
        session.commit()


@contextmanager
def claimed_scheduler_run(
    job_name: SchedulerJobName,
    period_key: str,
    agency_id: int = GLOBAL_SCHEDULER_AGENCY_ID,
) -> Iterator[int | None]:
    run_id = claim_scheduler_run(job_name, period_key, agency_id)
    if run_id is None:
        yield None
        return
    try:
        yield run_id
    except Exception as exc:
        finish_scheduler_run(run_id, SchedulerRunStatus.FAILED, str(exc))
        raise
    finish_scheduler_run(run_id, SchedulerRunStatus.SUCCESS)


def _poll_seconds() -> float:
    base = max(settings.scheduler_poll_seconds, 1)
    return max(base / current_speed(), 0.1)
