"""Small in-process scheduler for demo/runtime jobs."""

import os
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from flask import Flask
from loguru import logger
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.alerts.alert_service import generate_scheduled_alerts
from app.alerts.email_service import process_all_alerts
from app.auth.models import Agencies
from app.shared.clock import current_speed, utc_now
from app.shared.config import settings
from app.shared.database import get_session
from app.shared.models import SchedulerRun

GLOBAL_SCHEDULER_AGENCY_ID = 0
EMAIL_JOB_NAME = "process_alert_emails"
INVENTORY_AUDIT_JOB_NAME = "generate_inventory_alerts"
JOB_STARTED = "started"
JOB_SUCCESS = "success"
JOB_FAILED = "failed"
INVENTORY_AUDIT_LOCAL_HOUR = 7
INVENTORY_AUDIT_LOCAL_MINUTE = 45

_started = False


def start_scheduler(app: Flask) -> None:
    """Start background jobs when explicitly enabled."""
    global _started
    if _started or not settings.scheduler_enabled or _is_reloader_parent(app):
        return
    if settings.is_prod:
        logger.warning("In-process scheduler disabled in prod; use Railway cron")
        return

    _started = True
    thread = threading.Thread(target=_run_loop, args=(app,), daemon=True)
    thread.start()
    logger.info(
        "Development background scheduler started",
        extra={"poll_seconds": settings.scheduler_poll_seconds},
    )


def _run_loop(app: Flask) -> None:
    while True:
        try:
            with app.app_context():
                _run_due_jobs()
        except Exception:
            logger.exception("Scheduler job failed")
        time.sleep(_poll_seconds())


def _run_due_jobs() -> None:
    now = utc_now()
    _run_daily_inventory_job(now)
    _run_hourly_email_job(now)


def _run_hourly_email_job(now: datetime) -> None:
    hour_key = now.strftime("%Y-%m-%dT%H")
    run_id = _claim_scheduler_run(EMAIL_JOB_NAME, hour_key)
    if run_id is None:
        return

    try:
        result = process_all_alerts()
    except Exception as exc:
        _finish_scheduler_run(run_id, JOB_FAILED, str(exc))
        raise

    _finish_scheduler_run(run_id, JOB_SUCCESS)
    logger.info("Hourly alert email job complete", extra=result)


def _run_daily_inventory_job(now: datetime) -> None:
    total = 0
    for agency_id, timezone in _active_agency_schedules():
        period_key = _inventory_audit_period_key(now, timezone)
        if period_key is None:
            continue

        run_id = _claim_scheduler_run(INVENTORY_AUDIT_JOB_NAME, period_key, agency_id)
        if run_id is None:
            continue

        try:
            total += _generate_agency_inventory_alerts(agency_id)
            _finish_scheduler_run(run_id, JOB_SUCCESS)
        except Exception as exc:
            _finish_scheduler_run(run_id, JOB_FAILED, str(exc))
            logger.exception(
                "Scheduler inventory audit failed",
                extra={"agency_id": agency_id, "period_key": period_key},
            )
    if total:
        logger.info("Daily inventory alert audit job complete", extra={"rows_checked": total})


def _active_agency_schedules() -> list[tuple[int, str]]:
    with get_session() as session:
        rows = session.execute(
            select(Agencies.id, Agencies.timezone).where(Agencies.active.is_(True))
        ).all()
        return [(agency_id, timezone or "UTC") for agency_id, timezone in rows]


def _inventory_audit_period_key(now: datetime, timezone: str) -> str | None:
    local_now = now.astimezone(ZoneInfo(timezone))
    if (local_now.hour, local_now.minute) < (
        INVENTORY_AUDIT_LOCAL_HOUR,
        INVENTORY_AUDIT_LOCAL_MINUTE,
    ):
        return None
    return local_now.strftime("%Y-%m-%d")


def _generate_agency_inventory_alerts(agency_id: int) -> int:
    with get_session() as session:
        count = generate_scheduled_alerts(session, agency_id)
        session.commit()
        return count


def _claim_scheduler_run(
    job_name: str,
    period_key: str,
    agency_id: int = GLOBAL_SCHEDULER_AGENCY_ID,
) -> int | None:
    with get_session() as session:
        existing_id = session.scalar(
            select(SchedulerRun.id).where(
                SchedulerRun.job_name == job_name,
                SchedulerRun.agency_id == agency_id,
                SchedulerRun.period_key == period_key,
            )
        )
        if existing_id is not None:
            return None

        run = SchedulerRun(
            job_name=job_name,
            agency_id=agency_id,
            period_key=period_key,
            status=JOB_STARTED,
        )
        session.add(run)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            return None
        return run.id


def _finish_scheduler_run(run_id: int, status: str, error: str | None = None) -> None:
    with get_session() as session:
        run = session.get(SchedulerRun, run_id)
        if run is None:
            logger.warning("Scheduler run marker missing", extra={"scheduler_run_id": run_id})
            return
        run.status = status
        run.finished_at = utc_now().replace(tzinfo=None)
        run.error = error[:1000] if error else None
        session.commit()


def _is_reloader_parent(app: Flask) -> bool:
    return app.debug and os.environ.get("WERKZEUG_RUN_MAIN") != "true"


def _poll_seconds() -> float:
    base = max(settings.scheduler_poll_seconds, 1)
    return max(base / current_speed(), 0.1)
