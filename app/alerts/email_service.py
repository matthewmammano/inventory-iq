from datetime import datetime
from typing import Dict

from flask import current_app, render_template
from flask_mail import Message

from app import db, mail
from app.alerts.models import Alert, EmailBatch
from app.auth.models import UserAlerts, Users


class EmailBatchService:
    """Handles email batching and sending"""

    @staticmethod
    def should_send_email(user_alerts: UserAlerts) -> bool:
        """Check if it's time to send based on grouping hours"""
        print(f"[EMAIL DEBUG] should_send_email called for user_id={user_alerts.user_id}")
        print(
            f"[EMAIL DEBUG] Pending alerts count: {len(user_alerts.pending_alerts) if user_alerts.pending_alerts else 0}"
        )
        if not user_alerts.pending_alerts:
            return False
        if not user_alerts.last_sent:
            return True
        hours_since = (datetime.now() - user_alerts.last_sent).total_seconds() / 3600
        should_send = hours_since >= user_alerts.alert_grouping_hours
        print(
            f"[EMAIL DEBUG] Hours since last sent: {hours_since:.2f}, grouping hours: {user_alerts.alert_grouping_hours}, should send: {should_send}"
        )
        return should_send

    @staticmethod
    def create_email_batch(user_alerts: UserAlerts) -> EmailBatch:
        """Convert pending alerts to EmailBatch for sending"""
        print(f"[EMAIL DEBUG] create_email_batch called for user_id={user_alerts.user_id}")
        user = db.session.get(Users, user_alerts.user_id)
        print(f"[EMAIL DEBUG] User found: {user.email if user else 'None'}")
        alerts = [Alert(**alert_dict) for alert_dict in user_alerts.pending_alerts]
        print(f"[EMAIL DEBUG] Created {len(alerts)} Alert objects from pending alerts")

        email_batch = EmailBatch(alerts=alerts, user_email=user.email, user_name=user.display_name)
        print(f"[EMAIL DEBUG] EmailBatch created with subject: {email_batch.subject}")
        return email_batch

    @staticmethod
    def send_batch_email(user_id: int) -> bool:
        """Send batched email and clear pending alerts

        Returns:
            bool: True if email was sent successfully
        """
        print(f"[EMAIL DEBUG] send_batch_email called for user_id={user_id}")
        try:
            user_alerts = UserAlerts.query.filter_by(user_id=user_id).first()
            print(f"[EMAIL DEBUG] UserAlerts found: {user_alerts is not None}")
            if not user_alerts or not EmailBatchService.should_send_email(user_alerts):
                return False

            # Create email batch
            print("[EMAIL DEBUG] Creating email batch...")
            email_batch = EmailBatchService.create_email_batch(user_alerts)

            # Create Flask-Mail message
            print("[EMAIL DEBUG] Creating Flask-Mail message...")
            print(f"[EMAIL DEBUG] Subject: {email_batch.subject}")
            print(f"[EMAIL DEBUG] Sender: {current_app.config.get('MAIL_DEFAULT_SENDER', 'NOT_SET')}")
            print(f"[EMAIL DEBUG] Recipients: {[email_batch.user_email]}")
            msg = Message(
                subject=email_batch.subject,
                sender=current_app.config["MAIL_DEFAULT_SENDER"],
                recipients=[email_batch.user_email],
            )

            # Render email templates from alerts/templates folder
            print("[EMAIL DEBUG] Rendering email templates...")
            try:
                # Use the template names directly since blueprint has template_folder='templates'
                msg.html = render_template("batch_email.html", batch=email_batch)
                msg.body = render_template("batch_email.txt", batch=email_batch)
                print("[EMAIL DEBUG] Templates rendered successfully")
            except Exception as template_error:
                print(f"[EMAIL DEBUG] Template error: {template_error}")
                # Fallback to simple text email
                msg.body = f"Subject: {email_batch.subject}\\n\\nYou have {len(email_batch.alerts)} inventory alerts."
                print("[EMAIL DEBUG] Using fallback text email")

            # Send email
            print("[EMAIL DEBUG] Attempting to send email via Flask-Mail...")
            mail.send(msg)  # TODO PINK: suppress output from here of send / replies from SMTP server
            print("[EMAIL DEBUG] Email sent successfully!")

            # Clear pending alerts and mark sent
            user_alerts.pending_alerts = []
            user_alerts.last_sent = datetime.now()
            db.session.commit()

            current_app.logger.info(
                f"Sent batch email with {len(email_batch.alerts)} alerts to {email_batch.user_email}"
            )
            print("[EMAIL DEBUG] send_batch_email completed successfully")
            return True

        except Exception as e:
            print(f"[EMAIL DEBUG] ERROR in send_batch_email: {e}")
            print(f"[EMAIL DEBUG] Exception type: {type(e).__name__}")
            current_app.logger.error(f"Failed to send batch email for user {user_id}: {e}")
            return False

    @staticmethod
    def process_all_alerts() -> Dict[str, int]:
        """Process alerts for all users - for cron job

        Returns:
            Dict with processing stats: {"processed": int, "sent": int, "errors": int}
        """
        print("[EMAIL DEBUG] process_all_alerts called")
        stats = {"processed": 0, "sent": 0, "errors": 0}

        try:
            users_with_alerts = UserAlerts.query.filter(UserAlerts.pending_alerts != []).all()
            stats["processed"] = len(users_with_alerts)
            print(f"[EMAIL DEBUG] Found {len(users_with_alerts)} users with pending alerts")

            for user_alerts in users_with_alerts:
                print(f"[EMAIL DEBUG] Processing user_id={user_alerts.user_id}")
                if EmailBatchService.should_send_email(user_alerts):
                    print(f"[EMAIL DEBUG] Sending email for user_id={user_alerts.user_id}")
                    if EmailBatchService.send_batch_email(user_alerts.user_id):
                        stats["sent"] += 1
                        print(f"[EMAIL DEBUG] Email sent successfully for user_id={user_alerts.user_id}")
                    else:
                        stats["errors"] += 1
                        print(f"[EMAIL DEBUG] Email failed for user_id={user_alerts.user_id}")
                else:
                    print(f"[EMAIL DEBUG] Skipping email for user_id={user_alerts.user_id} (conditions not met)")

            current_app.logger.info(f"Alert processing complete: {stats}")
            print(f"[EMAIL DEBUG] process_all_alerts completed: {stats}")
            return stats

        except Exception as e:
            print(f"[EMAIL DEBUG] ERROR in process_all_alerts: {e}")
            print(f"[EMAIL DEBUG] Exception type: {type(e).__name__}")
            current_app.logger.error(f"Error in process_all_alerts: {e}")
            stats["errors"] += 1
            return stats
