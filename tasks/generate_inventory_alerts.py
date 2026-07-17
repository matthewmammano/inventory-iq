"""Run the full inventory alert safety audit.

Production task: python -m tasks.generate_inventory_alerts
"""

from app import create_app
from app.alerts.alert_service import generate_scheduled_alerts
from app.shared.database import get_session
from app.shared.scheduler import SchedulerJobName, run_scheduled_task


def run() -> None:
    """Generate safety-audit alert rows for all active agencies."""
    app = create_app()
    with app.app_context(), run_scheduled_task("generate_inventory_alerts", SchedulerJobName.GENERATE_INVENTORY_ALERTS) as task_result:
        if task_result is None:
            return
        with get_session() as session:
            count = generate_scheduled_alerts(session)
            session.commit()
            task_result["rows_checked"] = count


if __name__ == "__main__":
    run()
