"""
Send summary reports to users.
Cron: 0 6 * * * python -m app.tasks.generate_summary_reports daily
"""

import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Tuple

from flask import current_app
from flask_mailman import EmailMessage
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
            print(f"Unknown report type: {report_type}")
            return

        days, filter_condition = config
        users = Users.query.join(UserAlerts).filter(filter_condition).all()
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        sent = 0
        for user in users:
            action_count = ActionLogs.query.filter(
                and_(ActionLogs.user_id == user.id, ActionLogs.time_scanned >= cutoff)
            ).count()

            if action_count > 0:
                _send_report_email(user, report_type, action_count, cutoff)
                sent += 1

        print(f"Sent {sent} {report_type} reports")


def _get_report_config(report_type: str) -> Optional[Tuple[int, Any]]:
    """Get configuration for report type."""
    configs = {
        "daily": (1, UserAlerts.daily_summary.is_(True)),
        "weekly": (7, UserAlerts.weekly_summary.is_(True)),
        "monthly": (30, UserAlerts.monthly_summary.is_(True)),
    }
    return configs.get(report_type)


def _send_report_email(user: Users, report_type: str, count: int, cutoff: datetime) -> None:
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
    mail.send(msg)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        generate_summary_reports(sys.argv[1])
    else:
        print("Usage: python -m app.tasks.generate_summary_reports <daily|weekly|monthly>")
