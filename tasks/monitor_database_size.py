"""Monthly database size monitoring report.
Cron: 0 9 1 * * python tasks/monitor_database_size.py
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from flask import current_app
from flask_mailman import EmailMessage
from loguru import logger
from sqlalchemy import func, select

from app import create_app
from app.auth.models import Agencies
from app.inventory.models import ActionLogs, Items
from app.shared.database import get_session


def monitor_database_size() -> None:
    app = create_app()
    with app.app_context():
        db_size_mb = _db_size_mb(app)
        stats = _stats()
        admin_email = current_app.config.get("MAIL_DEFAULT_SENDER") or _fallback_email()

        if not admin_email:
            logger.warning("No admin email configured")
            return

        _send_report(admin_email, db_size_mb, stats)
        logger.info(f"DB report sent: {db_size_mb} MB, {stats}")


def _db_size_mb(app) -> float:
    path = Path(app.instance_path) / "inventory_iq.db"
    return round(path.stat().st_size / 1024 / 1024, 2) if path.exists() else 0.0


def _stats() -> dict:
    thirty_ago = datetime.now(UTC) - timedelta(days=30)
    with get_session() as s:
        return {
            "agencies": int(
                s.execute(
                    select(func.count()).select_from(Agencies).where(Agencies.active.is_(True))
                ).scalar()
                or 0
            ),
            "items": int(
                s.execute(
                    select(func.count()).select_from(Items).where(Items.active.is_(True))
                ).scalar()
                or 0
            ),
            "recent_actions": int(
                s.execute(
                    select(func.count())
                    .select_from(ActionLogs)
                    .where(ActionLogs.time_scanned >= thirty_ago)
                ).scalar()
                or 0
            ),
        }


def _fallback_email() -> str | None:
    with get_session() as s:
        agency = (
            s.execute(select(Agencies).where(Agencies.active.is_(True)).limit(1)).scalars().first()
        )
        return agency.email if agency else None


def _send_report(to: str, size_mb: float, stats: dict) -> None:
    body = (
        f"Monthly Database Report\n"
        f"=======================\n"
        f"Size:             {size_mb} MB\n"
        f"Active Agencies:  {stats['agencies']}\n"
        f"Active Items:     {stats['items']}\n"
        f"Actions (30d):    {stats['recent_actions']}\n"
        f"Generated:        {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    msg = EmailMessage(
        subject=f"Monthly Database Report — {datetime.now().strftime('%B %Y')}",
        body=body,
        from_email=current_app.config.get("MAIL_DEFAULT_SENDER"),
        to=[to],
    )
    msg.send()


if __name__ == "__main__":
    monitor_database_size()
