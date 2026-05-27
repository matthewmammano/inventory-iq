"""Send all currently pending alert emails.

Production task: python -m tasks.process_email_alerts
"""

from loguru import logger

from app import create_app
from app.alerts.email_service import process_all_alerts


def run() -> None:
    """Send all pending alert emails."""
    app = create_app()
    with app.app_context():
        result = process_all_alerts(force=True)
        logger.info(
            "Alert batch: "
            f"processed={result['processed']} sent={result['sent']} failed={result['failed']}"
        )


if __name__ == "__main__":
    run()
