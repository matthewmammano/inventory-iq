"""Small in-process scheduler for local/demo runtime jobs."""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from flask import Flask
from loguru import logger
from sqlalchemy import select

from app.alerts.alert_service import generate_scheduled_alerts
from app.alerts.email_service import process_all_alerts
from app.auth.models import Agencies
from app.shared.clock import current_speed, utc_now
from app.shared.config import settings
from app.shared.database import get_session

STATE_FILE = Path(__file__).resolve().parents[2] / "instance" / "scheduler_state.json"
INVENTORY_AUDIT_LOCAL_HOUR = 7

_started = False


def start_scheduler(app: Flask) -> None:
    """Start background jobs when explicitly enabled."""
    global _started
    if _started or not settings.scheduler_enabled or _is_reloader_parent(app):
        return

    _started = True
    thread = threading.Thread(target=_run_loop, args=(app,), daemon=True)
    thread.start()
    logger.info("Scheduler started", extra={"poll_seconds": settings.scheduler_poll_seconds})


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
    state = _read_state()
    _run_daily_inventory_job(now, state)
    _run_hourly_email_job(now, state)
    _write_state(state)


def _run_hourly_email_job(now: datetime, state: dict[str, Any]) -> None:
    hour_key = now.strftime("%Y-%m-%dT%H")
    if state.get("email_hour") == hour_key:
        return
    result = process_all_alerts()
    state["email_hour"] = hour_key
    logger.info("Scheduler email job complete", extra=result)


def _run_daily_inventory_job(now: datetime, state: dict[str, Any]) -> None:
    inventory_days = state.setdefault("inventory_days", {})
    with get_session() as session:
        agencies = list(
            session.execute(select(Agencies).where(Agencies.active.is_(True))).scalars().all()
        )
        total = 0
        for agency in agencies:
            local_now = now.astimezone(ZoneInfo(agency.timezone or "UTC"))
            day_key = local_now.strftime("%Y-%m-%d")
            if (
                local_now.hour < INVENTORY_AUDIT_LOCAL_HOUR
                or inventory_days.get(str(agency.id)) == day_key
            ):
                continue
            total += generate_scheduled_alerts(session, agency.id)
            inventory_days[str(agency.id)] = day_key
        session.commit()

    if total:
        logger.info("Scheduler inventory audit complete", extra={"rows": total})


def _read_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Scheduler state reset: {}", exc)
        return {}


def _write_state(state: dict[str, Any]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _is_reloader_parent(app: Flask) -> bool:
    return app.debug and os.environ.get("WERKZEUG_RUN_MAIN") != "true"


def _poll_seconds() -> float:
    base = max(settings.scheduler_poll_seconds, 1)
    return max(base / current_speed(), 0.1)
