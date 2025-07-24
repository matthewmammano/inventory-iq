#!/usr/bin/env python3
"""
Cron job script to process batched email alerts.
Run hourly: 0 * * * * cd /path/to/inventory-iq && python -m app.tasks.process_email_alerts
"""

import sys
from typing import Any, Dict

from app import create_app
from app.alerts.email_service import EmailBatchService


def main() -> Dict[str, Any]:
    """Process all pending email alerts for users."""
    app = create_app()

    with app.app_context():
        try:
            result = EmailBatchService.process_all_alerts()

            # Log results for monitoring
            if result["total_users_processed"] > 0:
                print("Email alerts processed successfully:")
                print(f"  - Users processed: {result['total_users_processed']}")
                print(f"  - Emails sent: {result['emails_sent']}")
                print(f"  - Alerts cleared: {result['alerts_cleared']}")
            else:
                print("No users required email alert processing.")

            return result

        except Exception as e:
            print(f"Error processing email alerts: {str(e)}")
            sys.exit(1)


if __name__ == "__main__":
    main()
