"""
Send summary reports to users.
Cron: 0 6 * * * python -m app.tasks.generate_summary_reports daily
"""

import sys
from datetime import UTC, datetime, timedelta
from typing import Any

from flask import current_app
from flask_mailman import EmailMessage, Mail
from loguru import logger
from sqlalchemy import and_

from app import create_app, mail
from app.auth.models import UserAlerts, Users
from app.inventory.models import ActionLogs


def generate_summary_reports(report_type: str) -> None:
    """Generate and send summary reports to users."""
    app = create_app()

    with app.app_context():
        config = _get_report_config(report_type)
        if not config:
            logger.error(f"Unknown report type: {report_type}")
            return

        days, filter_condition = config
        from sqlalchemy import select

        from app.db import get_session

        with get_session() as session:
            stmt = select(Users).join(UserAlerts).where(filter_condition)
            users = session.execute(stmt).scalars().all()
        cutoff = datetime.now(UTC) - timedelta(days=days)

        sent = 0
        for user in users:
            with get_session() as session:
                from sqlalchemy import func, select

                count_stmt = (
                    select(func.count())
                    .select_from(ActionLogs)
                    .where(
                        and_(
                            ActionLogs.user_id == user.id,
                            ActionLogs.time_scanned >= cutoff,
                        )
                    )
                )
                action_count = int(session.execute(count_stmt).scalar() or 0)

            if action_count > 0:
                _send_report_email(user, report_type, action_count, cutoff)
                sent += 1

        logger.info(f"Sent {sent} {report_type} reports")


def _get_report_config(report_type: str) -> tuple[int, Any] | None:
    """Get configuration for report type."""
    configs = {
        "daily": (1, UserAlerts.daily_summary.is_(True)),
        "weekly": (7, UserAlerts.weekly_summary.is_(True)),
        "monthly": (30, UserAlerts.monthly_summary.is_(True)),
    }
    return configs.get(report_type)


def _send_report_email(
    user: Users, report_type: str, count: int, cutoff: datetime
) -> None:
    """Send report email to user."""
    body = f"""Hi {user.display_name},

Your {report_type} inventory summary:
- Total actions: {count}
- Period: {cutoff.date()} to {datetime.now().date()}

Thanks!"""

    msg = EmailMessage(
        subject=f"{report_type.title()} Inventory Summary",
        body=body,
        from_email=current_app.config["MAIL_DEFAULT_SENDER"],
        to=[user.email],
    )
    mail_obj: Mail = mail  # type: ignore[name-defined]
    if mail_obj is None:
        logger.error("Mail service not configured; cannot send summary report")
        return
    mail_obj.send(msg)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        generate_summary_reports(sys.argv[1])
    else:
        logger.error(
            "Usage: python -m app.tasks.generate_summary_reports <daily|weekly|monthly>"
        )
