import logging
from datetime import datetime
from typing import Dict

from flask import current_app, render_template
from flask_mailman import EmailMessage, EmailMultiAlternatives

from app import db, mail
from app.alerts.models import Alert, EmailBatch
from app.auth.models import UserAlerts, Users

logger = logging.getLogger(__name__)


class EmailBatchService:
    """Handles email batching and sending"""

    @staticmethod
    def should_send_email(user_alerts: UserAlerts) -> bool:
        """Check if it's time to send based on grouping hours"""
        logger.info(f"should_send_email called for user_id={user_alerts.user_id}")
        logger.info(
            f"Pending alerts count: {len(user_alerts.pending_alerts) if user_alerts.pending_alerts else 0}"
        )
        if not user_alerts.pending_alerts:
            return False
        if not user_alerts.last_sent:
            return True
        hours_since = (datetime.now() - user_alerts.last_sent).total_seconds() / 3600
        should_send = hours_since >= user_alerts.alert_grouping_hours
        logger.info(
            f"Hours since last sent: {hours_since:.2f}, grouping hours: {user_alerts.alert_grouping_hours}, should send: {should_send}"
        )
        return should_send

    @staticmethod
    def create_email_batch(user_alerts: UserAlerts) -> EmailBatch:
        """Convert pending alerts to EmailBatch for sending"""
        logger.info(f"create_email_batch called for user_id={user_alerts.user_id}")
        user = db.session.get(Users, user_alerts.user_id)
        logger.info(f"User found: {user.email if user else 'None'}")
        alerts = [Alert(**alert_dict) for alert_dict in user_alerts.pending_alerts]
        logger.info(f"Created {len(alerts)} Alert objects from pending alerts")

        email_batch = EmailBatch(alerts=alerts, user_email=user.email, user_name=user.display_name)
        logger.info(f"EmailBatch created with subject: {email_batch.subject}")
        return email_batch

    @staticmethod
    def send_batch_email(user_id: int) -> bool:
        """Send batched email and clear pending alerts

        Returns:
            bool: True if email was sent successfully
        """
        logger.info(f"send_batch_email called for user_id={user_id}")
        try:
            user_alerts = UserAlerts.query.filter_by(user_id=user_id).first()
            logger.info(f"UserAlerts found: {user_alerts is not None}")
            if not user_alerts or not EmailBatchService.should_send_email(user_alerts):
                return False

            # Create email batch
            logger.info("Creating email batch...")
            email_batch = EmailBatchService.create_email_batch(user_alerts)

            # Create Flask-Mailman message with best practices
            logger.info("Creating Flask-Mailman EmailMultiAlternatives message...")
            logger.info(f"Subject: {email_batch.subject}")
            logger.info(f"Sender: {current_app.config.get('MAIL_DEFAULT_SENDER', 'NOT_SET')}")
            logger.info(f"Recipients: {[email_batch.user_email]}")
            
            # Render email templates from alerts/templates folder
            logger.info("Rendering email templates...")
            try:
                # Use the template names directly since blueprint has template_folder='templates'
                text_content = render_template("batch_email.txt", batch=email_batch)
                html_content = render_template("batch_email.html", batch=email_batch)
                
                # Use EmailMultiAlternatives for best practice HTML + text emails
                msg = EmailMultiAlternatives(
                    subject=email_batch.subject,
                    body=text_content,  # Plain text version
                    from_email=current_app.config["MAIL_DEFAULT_SENDER"],
                    to=[email_batch.user_email],
                )
                # Attach HTML alternative
                msg.attach_alternative(html_content, "text/html")
                logger.info("Templates rendered successfully with HTML alternative")
            except Exception as template_error:
                logger.error(f"Template error: {template_error}")
                # Fallback to simple text email using EmailMessage
                msg = EmailMessage(
                    subject=email_batch.subject,
                    body=f"Subject: {email_batch.subject}\\n\\nYou have {len(email_batch.alerts)} inventory alerts.",
                    from_email=current_app.config["MAIL_DEFAULT_SENDER"],
                    to=[email_batch.user_email],
                )
                logger.warning("Using fallback text email")

            # Send email
            logger.info("Attempting to send email via Flask-Mailman...")
            mail.send(msg)
            logger.info("Email sent successfully!")

            # Clear pending alerts and mark sent
            user_alerts.pending_alerts = []
            user_alerts.last_sent = datetime.now()
            db.session.commit()

            current_app.logger.info(
                f"Sent batch email with {len(email_batch.alerts)} alerts to {email_batch.user_email}"
            )
            logger.info("send_batch_email completed successfully")
            return True

        except Exception as e:
            logger.error(f"ERROR in send_batch_email: {e}")
            logger.error(f"Exception type: {type(e).__name__}")
            current_app.logger.error(f"Failed to send batch email for user {user_id}: {e}")
            return False

    @staticmethod
    def process_all_alerts() -> Dict[str, int]:
        """Process alerts for all users - for cron job

        Returns:
            Dict with processing stats: {"processed": int, "sent": int, "errors": int}
        """
        logger.info("process_all_alerts called")
        stats = {"processed": 0, "sent": 0, "errors": 0}

        try:
            users_with_alerts = UserAlerts.query.filter(UserAlerts.pending_alerts != []).all()
            stats["processed"] = len(users_with_alerts)
            logger.info(f"Found {len(users_with_alerts)} users with pending alerts")

            for user_alerts in users_with_alerts:
                logger.info(f"Processing user_id={user_alerts.user_id}")
                if EmailBatchService.should_send_email(user_alerts):
                    logger.info(f"Sending email for user_id={user_alerts.user_id}")
                    if EmailBatchService.send_batch_email(user_alerts.user_id):
                        stats["sent"] += 1
                        logger.info(f"Email sent successfully for user_id={user_alerts.user_id}")
                    else:
                        stats["errors"] += 1
                        logger.error(f"Email failed for user_id={user_alerts.user_id}")
                else:
                    logger.info(f"Skipping email for user_id={user_alerts.user_id} (conditions not met)")

            current_app.logger.info(f"Alert processing complete: {stats}")
            logger.info(f"process_all_alerts completed: {stats}")
            return stats

        except Exception as e:
            logger.error(f"ERROR in process_all_alerts: {e}")
            logger.error(f"Exception type: {type(e).__name__}")
            current_app.logger.error(f"Error in process_all_alerts: {e}")
            stats["errors"] += 1
            return stats
