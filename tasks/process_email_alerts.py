"""Send due pending alert emails.

Production task: python -m tasks.process_email_alerts
"""

import argparse

from app import create_app
from app.alerts.email_service import process_all_alerts
from app.shared.scheduler import SchedulerJobName, run_scheduled_task, scheduler_email_period_key


def run(*, force: bool = False) -> None:
    """Send pending alert emails using the normal cadence unless forced."""
    app = create_app()
    with (
        app.app_context(),
        run_scheduled_task(
            "process_email_alerts",
            SchedulerJobName.PROCESS_ALERT_EMAILS,
            period_key_fn=scheduler_email_period_key,
            bypass_claim=force,
            force=force,
        ) as task_result,
    ):
        if task_result is not None:
            task_result.update(process_all_alerts(force=force))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Send pending alert emails.")
    parser.add_argument("--force", action="store_true", help="send all pending alerts now")
    run(force=parser.parse_args().force)
