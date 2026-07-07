"""Developer-facing operational alert emails."""

from flask import current_app
from loguru import logger

from app.alerts.models import NotificationEmailDelivery
from app.shared.email_addresses import email_domain
from app.shared.email_client import OutboundEmail, send_email


def send_developer_delivery_failure_alert(delivery: NotificationEmailDelivery) -> None:
    admin_email = str(current_app.config.get("ADMIN_ALERT_EMAIL") or "").strip()
    if not admin_email:
        return
    body = (
        "Urgent Inventory IQ email delivery failure\n\n"
        "Check Railway logs and the notification_email_deliveries table.\n\n"
        f"Delivery ID: {delivery.id}\n"
        f"Agency ID: {delivery.agency_id}\n"
        f"Notification Recipient ID: {delivery.notification_recipient_id}\n"
        f"Recipient Domain: {email_domain(delivery.recipient_email_snapshot)}\n"
        f"Send At: {delivery.send_at}\n"
        f"Attempt Count: {delivery.attempt_count}\n"
        f"Next Attempt At: {delivery.next_attempt_at}\n"
        f"Error Type: {delivery.last_error_type}\n"
    )
    sent = send_email(
        OutboundEmail(
            subject="[URGENT] Inventory IQ email delivery failure",
            text_body=body,
            to_email=admin_email,
        ),
        retry_delays_seconds=(),
    )
    if not sent:
        logger.error(
            "Developer delivery failure alert email failed",
            extra={"notification_email_delivery_id": delivery.id, "agency_id": delivery.agency_id},
        )
