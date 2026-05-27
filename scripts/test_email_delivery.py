"""Manual email provider smoke test.

Usage: python -m scripts.test_email_delivery recipient@example.com
"""

import argparse
import sys

from loguru import logger

from app import create_app
from app.shared.email_client import (
    EMAIL_RETRY_DELAYS_SECONDS,
    OutboundEmail,
    email_configured,
    send_email,
)


def run(to_email: str) -> bool:
    """Send one real provider email without touching alert records."""
    app = create_app()
    with app.app_context():
        recipient_domain = to_email.partition("@")[2] or "unknown"
        if not email_configured():
            logger.error("Email smoke test aborted: provider config incomplete")
            return False
        sent = send_email(
            OutboundEmail(
                subject="Inventory IQ Email Delivery Test",
                text_body="Inventory IQ email delivery test succeeded.",
                to_email=to_email,
            ),
            retry_delays_seconds=EMAIL_RETRY_DELAYS_SECONDS,
        )
        if sent:
            logger.info(f"Email smoke test sent: domain={recipient_domain}")
        else:
            logger.error(f"Email smoke test failed: domain={recipient_domain}")
        return sent


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Send one Inventory IQ test email.")
    parser.add_argument("to_email", help="Recipient email address for the test send.")
    return parser


if __name__ == "__main__":
    args = _parser().parse_args()
    sys.exit(0 if run(args.to_email) else 1)
