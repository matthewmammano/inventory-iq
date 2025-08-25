"""
Cron job script to process batched email alerts.
Run hourly: 0 * * * * cd /path/to/inventory-iq && python -m app.tasks.process_email_alerts
"""

import logging
import sys
from typing import Any, Dict

from app import create_app
from app.alerts.email_service import EmailBatchService

logger = logging.getLogger(__name__)


def main() -> Dict[str, Any]:
    """Process all pending email alerts for users."""
    app = create_app()

    with app.app_context():
        try:
            result = EmailBatchService.process_all_alerts()

            # Log results for monitoring
            if result["total_users_processed"] > 0:
                logger.info("Email alerts processed successfully:")
                logger.info(f"  - Users processed: {result['total_users_processed']}")
                logger.info(f"  - Emails sent: {result['emails_sent']}")
                logger.info(f"  - Alerts cleared: {result['alerts_cleared']}")
            else:
                logger.info("No users required email alert processing.")

            return result

        except Exception as e:
            logger.error(f"Error processing email alerts: {str(e)}")
            sys.exit(1)


if __name__ == "__main__":
    main()
