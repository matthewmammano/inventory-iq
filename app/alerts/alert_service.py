from __future__ import annotations

from datetime import datetime
from typing import Any

from loguru import logger
from sqlalchemy import select

from app.auth.models import UserAlerts
from app.db import get_session


class AlertQueueService:
    """Manages adding alerts to user queues"""

    @staticmethod
    def add_alert(
        user_id: int, alert_type: str, item_name: str, urgent: bool = False, **data: Any
    ) -> bool:
        """Add standardized alert to user's pending list

        Parameters
        ----------
        user_id : int
            User to alert
        alert_type : str
            One of: low_stock, zero_stock, expired_soon, rare_scan, count_admin
        item_name : str
            Name of the item
        urgent : bool, optional
            Whether this needs immediate attention, by default False
        **data : Any
            Values for message template (quantity, min_quantity, days, etc)

        Returns
        -------
        bool
            True if alert was added successfully
        """
        logger.info(
            f"add_alert called: user_id={user_id}, alert_type={alert_type}, item_name={item_name}, urgent={urgent}"
        )
        with get_session() as session:
            # Use SQLAlchemy 2.0 scalar query pattern for better type inference
            stmt = select(UserAlerts).filter_by(user_id=user_id)
            user_alerts: UserAlerts | None = session.scalars(stmt).one_or_none()

            logger.info(f"UserAlerts query result: {user_alerts}")
            if not user_alerts:
                logger.warning(f"No UserAlerts found for user_id {user_id}")
                logger.warning(f"No UserAlerts found for user_id {user_id}")
                return False

            alert_dict: dict[str, Any] = {
                "type": alert_type,
                "item": item_name,
                "data": data,
                "urgent": urgent,
                "created": datetime.now().isoformat(),
            }

            existing_alerts = user_alerts.pending_alerts or []
            updated_alerts = [*existing_alerts, alert_dict]
            user_alerts.pending_alerts = updated_alerts

            session.add(user_alerts)
            session.commit()
            logger.info(
                f"Database commit successful for add_alert; pending_alerts={len(updated_alerts)}"
            )

        logger.info(f"Added {alert_type} alert for {item_name} to user {user_id}")
        logger.info("add_alert completed successfully")
        return True

    @staticmethod
    def queue_alerts_for_user(alerts: list[dict[str, Any]], user_id: int) -> None:
        """Queue a list of alert dicts for a user. This is a small helper used by inventory operations.

        Parameters
        ----------
        alerts : list[dict[str, Any]]
            List of alert dictionaries
        user_id : int
            Target user id

        Returns
        -------
        None
        """
        if not alerts:
            logger.info("No alerts to queue")
            return

        with get_session() as session:
            logger.info(f"Queuing {len(alerts)} alerts for user {user_id}")
            # Use SQLAlchemy 2.0 scalar query pattern
            stmt = select(UserAlerts).filter_by(user_id=user_id)
            user_alerts: UserAlerts | None = session.scalars(stmt).one_or_none()

            if not user_alerts:
                logger.warning(f"No UserAlerts record found for user {user_id}")
                # No alert container for this user; silently skip
                return

            existing_alerts = user_alerts.pending_alerts or []
            logger.info(f"Current pending_alerts count: {len(existing_alerts)}")

            # IMPORTANT: assign a new list so SQLAlchemy detects JSON change
            updated_alerts = [*existing_alerts, *alerts]
            user_alerts.pending_alerts = updated_alerts
            logger.info(f"After append, pending_alerts count: {len(updated_alerts)}")
            session.add(user_alerts)
            session.commit()
            logger.info(f"Successfully committed {len(alerts)} alerts to database")
