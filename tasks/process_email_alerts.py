"""Send batched pending email alerts.
Cron: 0 * * * * python tasks/process_email_alerts.py
"""

from loguru import logger

from app import create_app
from app.alerts.email_service import process_all_alerts


def run() -> None:
    """Send all due pending alert emails."""
    app = create_app()
    with app.app_context():
        result = process_all_alerts()
        logger.info(f"Alert batch: processed={result['processed']} sent={result['sent']}")


if __name__ == "__main__":
    run()
