from datetime import datetime
from typing import Dict

from flask import current_app, render_template
from flask_mail import Message

from app import db, mail
from app.alerts.models import Alert, EmailBatch
from app.auth.models import UserAlerts, Users


class AlertService:
    """Core alert management service - handles queuing, batching, and sending alerts"""

    @staticmethod
    def add_alert(user_id: int, alert_type: str, item_name: str, urgent: bool = False, **data):
        """Add standardized alert to user's pending list

        Args:
            user_id: User to alert
            alert_type: One of: low_stock, zero_stock, expired_soon, rare_scan, recount_admin
            item_name: Name of the item
            urgent: Whether this needs immediate attention
            **data: Values for message template (quantity, min_quantity, days, etc)

        Returns:
            bool: True if alert was added successfully
        """
        user_alerts = UserAlerts.query.filter_by(user_id=user_id).first()
        if not user_alerts:
            current_app.logger.warning(f"No UserAlerts found for user_id {user_id}")
            return False

        alert_dict = {
            "type": alert_type,
            "item": item_name,
            "data": data,
            "urgent": urgent,
            "created": datetime.now().isoformat(),
        }

        # Initialize pending_alerts if None
        if user_alerts.pending_alerts is None:
            user_alerts.pending_alerts = []

        user_alerts.pending_alerts.append(alert_dict)
        
        # Mark the JSON column as modified for SQLAlchemy to detect the change
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(user_alerts, "pending_alerts")
        
        db.session.commit()

        current_app.logger.info(f"Added {alert_type} alert for {item_name} to user {user_id}")
        return True

    @staticmethod
    def should_send_email(user_alerts: UserAlerts) -> bool:
        """Check if it's time to send based on grouping hours"""
        if not user_alerts.pending_alerts:
            return False
        if not user_alerts.last_sent:
            return True
        hours_since = (datetime.now() - user_alerts.last_sent).total_seconds() / 3600
        return hours_since >= user_alerts.alert_grouping_hours

    @staticmethod
    def create_email_batch(user_alerts: UserAlerts) -> EmailBatch:
        """Convert pending alerts to EmailBatch for sending"""
        user = db.session.get(Users, user_alerts.user_id)
        alerts = [Alert(**alert_dict) for alert_dict in user_alerts.pending_alerts]

        return EmailBatch(alerts=alerts, user_email=user.email, user_name=user.display_name)

    @staticmethod
    def send_batch_email(user_id: int) -> bool:
        """Send batched email and clear pending alerts

        Returns:
            bool: True if email was sent successfully
        """
        try:
            user_alerts = UserAlerts.query.filter_by(user_id=user_id).first()
            if not user_alerts or not AlertService.should_send_email(user_alerts):
                return False

            # Create email batch
            email_batch = AlertService.create_email_batch(user_alerts)

            # Create Flask-Mail message
            msg = Message(
                subject=email_batch.subject,
                sender=current_app.config["MAIL_DEFAULT_SENDER"],
                recipients=[email_batch.user_email],
            )

            # Render email templates from alerts/templates folder
            msg.html = render_template("alerts/batch_email.html", batch=email_batch)
            msg.body = render_template("alerts/batch_email.txt", batch=email_batch)

            # Send email
            mail.send(msg)

            # Clear pending alerts and mark sent
            user_alerts.pending_alerts = []
            user_alerts.last_sent = datetime.now()
            db.session.commit()

            current_app.logger.info(
                f"Sent batch email with {len(email_batch.alerts)} alerts to {email_batch.user_email}"
            )
            return True

        except Exception as e:
            current_app.logger.error(f"Failed to send batch email for user {user_id}: {e}")
            return False

    @staticmethod
    def process_all_alerts() -> Dict[str, int]:
        """Process alerts for all users - for cron job

        Returns:
            Dict with processing stats: {"processed": int, "sent": int, "errors": int}
        """
        stats = {"processed": 0, "sent": 0, "errors": 0}

        try:
            users_with_alerts = UserAlerts.query.filter(UserAlerts.pending_alerts != []).all()
            stats["processed"] = len(users_with_alerts)

            for user_alerts in users_with_alerts:
                if AlertService.should_send_email(user_alerts):
                    if AlertService.send_batch_email(user_alerts.user_id):
                        stats["sent"] += 1
                    else:
                        stats["errors"] += 1

            current_app.logger.info(f"Alert processing complete: {stats}")
            return stats

        except Exception as e:
            current_app.logger.error(f"Error in process_all_alerts: {e}")
            stats["errors"] += 1
            return stats
