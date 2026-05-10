"""Monthly database size monitoring report.
Cron: 0 9 1 * * python tasks/monitor_database_size.py
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from flask import current_app
from loguru import logger
from sqlalchemy import func, select

from app import create_app
from app.auth.models import Agencies
from app.inventory.models import ActionLogs, Items
from app.shared.brevo_email import OutboundEmail, send_email
from app.shared.database import get_session


def monitor_database_size() -> None:
    app = create_app()
    with app.app_context():
        db_size_mb = _db_size_mb(app)
        stats = _stats()
        admin_email = current_app.config.get("BREVO_SENDER_EMAIL") or _fallback_email()

        if not admin_email:
            logger.warning("No admin email configured")
            return

        if _send_report(admin_email, db_size_mb, stats):
            logger.info(f"DB report sent: {db_size_mb} MB, {stats}")
            return
        logger.error("DB report send failed")


def _db_size_mb(app) -> float:
    path = Path(app.instance_path) / "inventory_iq.db"
    return round(path.stat().st_size / 1024 / 1024, 2) if path.exists() else 0.0


def _stats() -> dict[str, int]:
    thirty_ago = datetime.now(UTC) - timedelta(days=30)
    with get_session() as s:
        return {
            "agencies": _count(s, Agencies, Agencies.active.is_(True)),
            "items": _count(s, Items, Items.active.is_(True)),
            "recent_actions": _count(s, ActionLogs, ActionLogs.time_scanned >= thirty_ago),
        }


def _count(session, model, condition) -> int:
    query = select(func.count()).select_from(model).where(condition)
    return int(session.execute(query).scalar() or 0)


def _fallback_email() -> str | None:
    with get_session() as s:
        agency = (
            s.execute(select(Agencies).where(Agencies.active.is_(True)).limit(1)).scalars().first()
        )
        return agency.email if agency else None


def _send_report(to_email: str, size_mb: float, stats: dict[str, int]) -> bool:
    body = (
        "Monthly Database Report\n"
        "=======================\n"
        f"Size:             {size_mb} MB\n"
        f"Active Agencies:  {stats['agencies']}\n"
        f"Active Items:     {stats['items']}\n"
        f"Actions (30d):    {stats['recent_actions']}\n"
        f"Generated:        {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    return send_email(
        OutboundEmail(
            subject=f"Monthly Database Report - {datetime.now().strftime('%B %Y')}",
            text_body=body,
            to_email=to_email,
        )
    )


if __name__ == "__main__":
    monitor_database_size()
