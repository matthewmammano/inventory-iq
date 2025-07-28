import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)


class AlertDetectionService:
    """Detects when inventory conditions require alerts"""

    @staticmethod
    def check_quantity_alerts(user_id, item_id, updated_quantities, previous_quantities, is_admin_action=False):
        """Check for all types of inventory alerts based on user preferences."""

        # Import here to avoid circular imports
        from app.auth.models import UserAlerts
        from app.inventory.models import ActionLogs, Items

        logger.info(
            f"check_quantity_alerts called by user_id={user_id} on item_id={item_id} with quantity of {previous_quantities} to {updated_quantities}"
        )

        alerts = []
        item = Items.query.filter_by(id=item_id, user_id=user_id).first()
        user_alerts = UserAlerts.query.filter_by(user_id=user_id).first()

        if not item or not user_alerts:
            logger.warning("Missing item or user_alerts, returning empty alerts")
            return alerts

        logger.info(
            f"User alert preferences listed: zero_stock={user_alerts.zero_stock}, low_stock_days={user_alerts.low_stock_days}, rare_scan_days={user_alerts.rare_scan_days}"
        )

        for loc_id, new_qty in updated_quantities.items():
            old_qty = previous_quantities.get(loc_id, 0)
            logger.info(f"Checking location {loc_id}: old_qty={old_qty}, new_qty={new_qty}")

            # TODO RED: make this one predictive with linear regression INSTEAD!
            # HERE using user_alerts.low_stock_days

            # 1. Zero stock alert - immediate when hitting 0 if enabled
            if user_alerts.zero_stock and new_qty == 0 and old_qty > 0:
                logger.warning(f"ZERO STOCK ALERT: {item.name} at location {loc_id} went from {old_qty} to 0")
                alerts.append({"location_id": loc_id, "alert_type": "zero_stock", "quantity": new_qty, "urgent": True})

            # 2. Low stock alert - only if crossing below threshold
            if item.min_quantity is not None and new_qty < item.min_quantity and old_qty >= item.min_quantity:
                logger.warning(
                    f"LOW STOCK ALERT: {item.name} at location {loc_id} dropped from {old_qty} to {new_qty} (min: {item.min_quantity})"
                )
                alerts.append(
                    {
                        "location_id": loc_id,
                        "alert_type": "low_stock",
                        "quantity": new_qty,
                        "min_quantity": item.min_quantity,
                        "urgent": new_qty == 0,
                    }
                )

        # 3. Rare scan alert - check if enabled and item hasn't been scanned recently (excluding admin actions)
        if user_alerts.rare_scan_days and user_alerts.rare_scan_days > 0 and not is_admin_action:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=user_alerts.rare_scan_days)
            logger.info(f"Checking rare scan alert: looking for non-admin scans since {cutoff_date}")

            # Find the most recent non-admin action for this item by this user
            last_non_admin_scan = (
                ActionLogs.query.filter(
                    ActionLogs.user_id == user_id,
                    ActionLogs.item_id == item_id,
                    ~ActionLogs.admin_action,  # Exclude admin actions (use ~ for proper SQLAlchemy negation)
                    ActionLogs.time_scanned >= cutoff_date,
                )
                .order_by(ActionLogs.time_scanned.desc())
                .first()
            )

            logger.info(f"Query found non-admin scan: {last_non_admin_scan is not None}")

            if not last_non_admin_scan:
                logger.warning(
                    f"RARE SCAN ALERT: {item.name} hasn't been scanned by non-admin user in {user_alerts.rare_scan_days} days"
                )
                alerts.append(
                    {
                        "alert_type": "rare_scan",
                        "item_name": item.name,
                        "days": user_alerts.rare_scan_days,
                        "urgent": False,
                    }
                )
            else:
                days_since = (datetime.now(timezone.utc) - last_non_admin_scan.time_scanned).days
                logger.info(f"Last non-admin scan was {days_since} days ago, no rare scan alert needed")

        logger.info(f"Generated {len(alerts)} alerts: {alerts}")
        return alerts
