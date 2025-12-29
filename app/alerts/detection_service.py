from datetime import UTC, datetime, timedelta
from typing import Any

from loguru import logger


class AlertDetectionService:
    """Detects when inventory conditions require alerts."""

    @staticmethod
    def check_quantity_alerts(
        user_id: int,
        item_id: int,
        updated_quantities: dict[int, int],
        previous_quantities: dict[int, int],
        is_admin_action: bool = False,
    ) -> list[dict[str, Any]]:
        """Check for all types of inventory alerts based on user preferences.

        Notes
        -----
        Imports models and session helper inside the function to avoid circular
        import issues when this module is imported from other packages.
        """

        # Local imports to avoid circular dependencies
        from sqlalchemy import select

        from app.auth.models import UserAlerts
        from app.db import get_session
        from app.inventory.models import ActionLogs, Items

        logger.info(
            f"check_quantity_alerts called by user_id={user_id} on item_id={item_id} "
            f"with quantity from {previous_quantities} to {updated_quantities}"
        )

        alerts: list[dict[str, Any]] = []

        # Load item and user alert preferences
        with get_session() as session:
            item_stmt = (
                select(Items).where(Items.id == item_id).where(Items.user_id == user_id)
            )
            item = session.execute(item_stmt).scalars().first()

            ua_stmt = select(UserAlerts).where(UserAlerts.user_id == user_id)
            user_alerts = session.execute(ua_stmt).scalars().first()

        if not item or not user_alerts:
            logger.warning("Missing item or user_alerts, returning empty alerts")
            return alerts

        logger.info(
            f"User alert preferences: zero_stock={user_alerts.zero_stock}, "
            f"low_stock_days={user_alerts.low_stock_days}, rare_scan_days={user_alerts.rare_scan_days}"
        )

        for loc_id, new_qty in updated_quantities.items():
            old_qty = previous_quantities.get(loc_id, 0)
            logger.debug(
                f"Checking location {loc_id}: old_qty={old_qty}, new_qty={new_qty}"
            )

            # Predictive low stock alert using prediction engine if enabled
            if (
                getattr(user_alerts, "low_stock_days", None)
                and user_alerts.low_stock_days > 0
            ):
                try:
                    from app.prediction.prediction_engine import PredictionEngine

                    with get_session() as pred_session:
                        prediction_result = PredictionEngine.predict_usage(
                            pred_session, user_id, item_id, loc_id
                        )

                    if (
                        prediction_result
                        and getattr(prediction_result, "daily_usage_rate", 0) < 0
                    ):
                        daily_consumption = abs(prediction_result.daily_usage_rate)
                        min_threshold = item.min_quantity or 1

                        if daily_consumption > 0 and new_qty > min_threshold:
                            days_until_low = (
                                new_qty - min_threshold
                            ) / daily_consumption
                            if days_until_low <= user_alerts.low_stock_days:
                                logger.warning(
                                    "PREDICTIVE LOW STOCK: %s at location %s will be low in %.1f days",
                                    item.name,
                                    loc_id,
                                    days_until_low,
                                )
                                alerts.append(
                                    {
                                        "location_id": loc_id,
                                        "alert_type": "predictive_low_stock",
                                        "quantity": new_qty,
                                        "predicted_days": round(days_until_low, 1),
                                        "confidence": getattr(
                                            prediction_result, "confidence_score", None
                                        ),
                                        "urgent": days_until_low <= 3,
                                    }
                                )
                except Exception as exc:
                    logger.error(f"Predictive alert calculation failed: {exc}")

            # 1. Zero stock alert
            if user_alerts.zero_stock and new_qty == 0 and old_qty > 0:
                logger.warning(
                    f"ZERO STOCK ALERT: {item.name} at location {loc_id} went from {old_qty} to 0"
                )
                alerts.append(
                    {
                        "location_id": loc_id,
                        "alert_type": "zero_stock",
                        "quantity": new_qty,
                        "urgent": True,
                    }
                )

            # 2. Low stock alert
            if (
                item.min_quantity is not None
                and new_qty < item.min_quantity
                and old_qty >= item.min_quantity
            ):
                logger.warning(
                    "LOW STOCK ALERT: %s at location %s dropped from %s to %s (min: %s)",
                    item.name,
                    loc_id,
                    old_qty,
                    new_qty,
                    item.min_quantity,
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

        # 3. Rare scan alert
        if (
            getattr(user_alerts, "rare_scan_days", None)
            and user_alerts.rare_scan_days > 0
            and not is_admin_action
        ):
            cutoff_date = datetime.now(UTC) - timedelta(days=user_alerts.rare_scan_days)
            logger.info(
                f"Checking rare scan alert: looking for non-admin scans since {cutoff_date}"
            )

            from sqlalchemy import select as _select

            from app.db import get_session as _get_session

            with _get_session() as session:
                stmt = (
                    _select(ActionLogs)
                    .where(
                        ActionLogs.user_id == user_id,
                        ActionLogs.item_id == item_id,
                        ~ActionLogs.admin_action,
                        ActionLogs.time_scanned >= cutoff_date,
                    )
                    .order_by(ActionLogs.time_scanned.desc())
                )
                last_non_admin_scan = session.execute(stmt).scalars().first()

            if not last_non_admin_scan:
                logger.warning(
                    f"RARE SCAN ALERT: {item.name} hasn't been scanned by non-admin user "
                    f"in {user_alerts.rare_scan_days} days"
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
                days_since = (datetime.now(UTC) - last_non_admin_scan.time_scanned).days
                logger.debug(f"Last non-admin scan was {days_since} days ago")

        logger.info(f"Generated {len(alerts)} alerts")
        return alerts
