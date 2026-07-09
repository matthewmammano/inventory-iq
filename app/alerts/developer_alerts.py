"""Developer-facing operational alert emails."""

from flask import current_app
from loguru import logger

from app.alerts.models import EmailDelivery
from app.shared.email_addresses import email_domain
from app.shared.email_client import OutboundEmail, send_email


def send_developer_delivery_failure_alert(delivery: EmailDelivery) -> None:
    """Email the admin about a failed delivery, at most once per 30-minute window."""
    admin_email = str(current_app.config.get("ADMIN_ALERT_EMAIL") or "").strip()
    if not admin_email or not _claim_developer_alert_window():
        return
    body = (
        "Urgent Inventory IQ email delivery failure\n\n"
        "Check Railway logs and the email_deliveries table.\n\n"
        f"Delivery ID: {delivery.id}\n"
        f"Agency ID: {delivery.agency_id}\n"
        f"Notification Recipient ID: {delivery.notification_recipient_id}\n"
        f"Recipient Domain: {email_domain(delivery.recipient_email_snapshot)}\n"
        f"Delivery Kind: {delivery.kind.value}\n"
        f"Error Type: {delivery.error_type}\n"
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


def _claim_developer_alert_window() -> bool:
    # Lazy import: scheduler imports the alert services at module load, so a
    # top-level import here would create a cycle.
    from app.shared.scheduler import SchedulerJobName, claim_scheduler_run, scheduler_developer_alert_period_key

    return claim_scheduler_run(SchedulerJobName.DEVELOPER_DELIVERY_ALERT, scheduler_developer_alert_period_key()) is not None
