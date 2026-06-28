"""Run the full inventory alert safety audit.

Production task: python -m tasks.generate_inventory_alerts
"""

from app import create_app
from app.alerts.alert_service import generate_scheduled_alerts
from app.shared.database import get_session
from app.shared.scheduler import INVENTORY_AUDIT_JOB_NAME, claimed_scheduler_run, scheduler_daily_period_key
from app.shared.task_logging import logged_task


def run() -> None:
    """Generate safety-audit alert rows for all active agencies."""
    app = create_app()
    with app.app_context(), get_session() as session, logged_task("generate_inventory_alerts") as task_result:
        period_key = scheduler_daily_period_key()
        with claimed_scheduler_run(INVENTORY_AUDIT_JOB_NAME, period_key) as run_id:
            if run_id is None:
                task_result["skipped"] = "already_claimed"
                return
            task_result["period_key"] = period_key
            count = generate_scheduled_alerts(session)
            session.commit()
            task_result["rows_checked"] = count


if __name__ == "__main__":
    run()
