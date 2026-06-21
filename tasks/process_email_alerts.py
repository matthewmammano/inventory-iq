"""Send due pending alert emails.

Production task: python -m tasks.process_email_alerts
"""

import argparse

from app import create_app
from app.alerts.email_service import process_all_alerts
from app.shared.task_logging import logged_task


def run(*, force: bool = False) -> None:
    """Send pending alert emails using the normal cadence unless forced."""
    app = create_app()
    with app.app_context(), logged_task("process_email_alerts", force=force) as task_result:
        result = process_all_alerts(force=force)
        task_result.update(result)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Send pending alert emails.")
    parser.add_argument("--force", action="store_true", help="send all pending alerts now")
    run(force=parser.parse_args().force)
