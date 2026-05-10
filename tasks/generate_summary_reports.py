"""Send daily/weekly summary reports to agencies.
Cron: 0 6 * * * python tasks/generate_summary_reports.py daily
      0 6 * * 1 python tasks/generate_summary_reports.py weekly
"""

import sys
from datetime import UTC, datetime, timedelta

from flask import current_app
from flask_mailman import EmailMessage
from loguru import logger
from sqlalchemy import and_, func, select

from app import create_app
from app.auth.models import Agencies, AgencyEmails
from app.inventory.models import ActionLogs
from app.shared.database import get_session


def generate_summary_reports(report_type: str) -> None:
    if report_type not in ("daily", "weekly"):
        logger.error(f"Unknown report type: {report_type}")
        return

    app = create_app()
    with app.app_context():
        days = 1 if report_type == "daily" else 7
        flag_col = (
            AgencyEmails.daily_summary if report_type == "daily" else AgencyEmails.weekly_summary
        )
        cutoff = datetime.now(UTC) - timedelta(days=days)

        with get_session() as s:
            # Find all agency emails opted into this report type
            opted_in = list(
                s.execute(select(AgencyEmails).where(flag_col.is_(True))).scalars().all()
            )

        sent = 0
        for ae in opted_in:
            with get_session() as s:
                count = int(
                    s.execute(
                        select(func.count())
                        .select_from(ActionLogs)
                        .where(
                            and_(
                                ActionLogs.agency_id == ae.agency_id,
                                ActionLogs.time_scanned >= cutoff,
                            )
                        )
                    ).scalar()
                    or 0
                )
                agency = s.get(Agencies, ae.agency_id)

            if count > 0 and agency:
                _send_report(ae.email, agency.display_name, report_type, count, cutoff)
                sent += 1

        logger.info(f"Sent {sent} {report_type} summary reports")


def _send_report(email: str, name: str, report_type: str, count: int, cutoff: datetime) -> None:
    body = (
        f"Hi {name},\n\n"
        f"Your {report_type} inventory summary:\n"
        f"  Total actions: {count}\n"
        f"  Period: {cutoff.date()} to {datetime.now().date()}\n\n"
        f"Thanks!"
    )
    msg = EmailMessage(
        subject=f"{report_type.title()} Inventory Summary",
        body=body,
        from_email=current_app.config.get("MAIL_DEFAULT_SENDER"),
        to=[email],
    )
    msg.send()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        generate_summary_reports(sys.argv[1])
    else:
        logger.error("Usage: python generate_summary_reports.py <daily|weekly>")
