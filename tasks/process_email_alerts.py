"""Send due pending alert emails.

Production task: python -m tasks.process_email_alerts
"""

import argparse

from loguru import logger

from app import create_app
from app.alerts.email_service import process_all_alerts


def run(*, force: bool = False) -> None:
    """Send pending alert emails using the normal cadence unless forced."""
    app = create_app()
    with app.app_context():
        result = process_all_alerts(force=force)
        logger.info("Alert batch: " f"force={force} processed={result['processed']} " f"sent={result['sent']} failed={result['failed']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Send pending alert emails.")
    parser.add_argument("--force", action="store_true", help="send all pending alerts now")
    run(force=parser.parse_args().force)
