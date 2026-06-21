"""Send daily/weekly summary reports to agencies.
Cron: 0 6 * * * python -m tasks.generate_summary_reports daily
      0 6 * * 1 python -m tasks.generate_summary_reports weekly
"""

import sys
from datetime import UTC, datetime, timedelta

from loguru import logger
from sqlalchemy import and_, func, select

from app import create_app
from app.auth.models import Agencies, AgencyEmails
from app.inventory.models import ActionLogs
from app.shared.database import get_session
from app.shared.email_client import EMAIL_RETRY_DELAYS_SECONDS, OutboundEmail, send_email
from app.shared.task_logging import logged_task


def generate_summary_reports(report_type: str) -> None:
    if report_type not in ("daily", "weekly"):
        logger.error("Summary report task rejected unknown report type", extra={"report_type": report_type})
        return

    app = create_app()
    with app.app_context(), logged_task("generate_summary_reports", report_type=report_type) as task_result:
        days = 1 if report_type == "daily" else 7
        flag_col = AgencyEmails.daily_summary if report_type == "daily" else AgencyEmails.weekly_summary
        cutoff = datetime.now(UTC) - timedelta(days=days)

        with get_session() as s:
            opted_in = list(s.execute(select(AgencyEmails).where(flag_col.is_(True))).scalars().all())
        logger.debug("Summary report recipients loaded", extra={"report_type": report_type, "recipient_count": len(opted_in)})

        sent = 0
        skipped = 0
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

            logger.debug("Summary report recipient evaluated", extra={"agency_id": ae.agency_id, "agency_email_id": ae.id, "action_count": count})
            if count > 0 and agency and _send_report(ae.email, agency.display_name, report_type, count, cutoff):
                sent += 1
            else:
                skipped += 1

        task_result.update({"recipient_count": len(opted_in), "sent": sent, "skipped": skipped})


def _send_report(email: str, name: str, report_type: str, count: int, cutoff: datetime) -> bool:
    body = (
        f"Hi {name},\n\n"
        f"Your {report_type} inventory summary:\n"
        f"  Total actions: {count}\n"
        f"  Period: {cutoff.date()} to {datetime.now().date()}\n\n"
        f"Thanks!"
    )
    return send_email(
        OutboundEmail(
            subject=f"{report_type.title()} Inventory Summary",
            text_body=body,
            to_email=email,
        ),
        retry_delays_seconds=EMAIL_RETRY_DELAYS_SECONDS,
    )


if __name__ == "__main__":
    if len(sys.argv) > 1:
        generate_summary_reports(sys.argv[1])
    else:
        logger.error("Summary report task requires an argument: <daily|weekly>")
