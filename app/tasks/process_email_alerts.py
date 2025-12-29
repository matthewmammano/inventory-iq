"""
Process batched email alerts hourly.
Cron: 0 * * * * python -m app.tasks.process_email_alerts
"""

from loguru import logger

from app import create_app
from app.alerts.email_service import EmailBatchService


def process_email_alerts():
    """Send pending email alerts to users"""
    app = create_app()
    with app.app_context():
        result = EmailBatchService.process_all_alerts()

        users_processed = result.get("total_users_processed", 0)
        emails_sent = result.get("emails_sent", 0)

        logger.info(f"Processed {users_processed} users, sent {emails_sent} emails")
        return result


if __name__ == "__main__":
    process_email_alerts()
