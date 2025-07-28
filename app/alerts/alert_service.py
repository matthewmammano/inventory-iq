import logging
from datetime import datetime

from flask import current_app
from sqlalchemy.orm.attributes import flag_modified

from app import db
from app.auth.models import UserAlerts

logger = logging.getLogger(__name__)


class AlertQueueService:
    """Manages adding alerts to user queues"""

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
        logger.info(
            f"add_alert called: user_id={user_id}, alert_type={alert_type}, item_name={item_name}, urgent={urgent}"
        )
        user_alerts = UserAlerts.query.filter_by(user_id=user_id).first()
        logger.info(f"UserAlerts query result: {user_alerts}")
        if not user_alerts:
            logger.warning(f"No UserAlerts found for user_id {user_id}")
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

        logger.info(f"Adding alert to pending list. Current count: {len(user_alerts.pending_alerts)}")
        user_alerts.pending_alerts.append(alert_dict)
        logger.info(f"Alert added. New count: {len(user_alerts.pending_alerts)}")

        # Mark the JSON column as modified for SQLAlchemy to detect the change
        flag_modified(user_alerts, "pending_alerts")

        db.session.commit()
        logger.info("Database commit successful for add_alert")

        current_app.logger.info(f"Added {alert_type} alert for {item_name} to user {user_id}")
        logger.info("add_alert completed successfully")
        return True
