from datetime import datetime, timedelta, timezone


class AlertDetectionService:
    """Detects when inventory conditions require alerts"""

    @staticmethod
    def check_quantity_alerts(user_id, item_id, updated_quantities, previous_quantities, is_admin_action=False):
        """Check for all types of inventory alerts based on user preferences."""

        # Import here to avoid circular imports
        from app.auth.models import UserAlerts
        from app.inventory.models import ActionLogs, Items

        print(f"[EMAIL DEBUG] check_quantity_alerts called: user_id={user_id}, item_id={item_id}")
        print(f"[EMAIL DEBUG] updated_quantities={updated_quantities}, previous_quantities={previous_quantities}")

        alerts = []
        item = Items.query.filter_by(id=item_id, user_id=user_id).first()
        user_alerts = UserAlerts.query.filter_by(user_id=user_id).first()

        print(
            f"[EMAIL DEBUG] Item found: {item.name if item else 'None'}, min_quantity={item.min_quantity if item else 'None'}"
        )
        print(f"[EMAIL DEBUG] UserAlerts found: {user_alerts is not None}")

        if not item or not user_alerts:
            print("[EMAIL DEBUG] Missing item or user_alerts, returning empty alerts")
            return alerts

        print(
            f"[EMAIL DEBUG] User alert preferences: zero_stock={user_alerts.zero_stock}, low_stock_days={user_alerts.low_stock_days}, rare_scan_days={user_alerts.rare_scan_days}"
        )

        for loc_id, new_qty in updated_quantities.items():
            old_qty = previous_quantities.get(loc_id, 0)
            print(f"[EMAIL DEBUG] Checking location {loc_id}: old_qty={old_qty}, new_qty={new_qty}")

            # TODO YELLOW: make this one predictive with linear regression INSTEAD!
            # 1. Zero stock alert - immediate when hitting 0 if enabled
            if user_alerts.zero_stock and new_qty == 0 and old_qty > 0:
                print(f"[EMAIL DEBUG] ZERO STOCK ALERT: {item.name} at location {loc_id} went from {old_qty} to 0")
                alerts.append({"location_id": loc_id, "alert_type": "zero_stock", "quantity": new_qty, "urgent": True})

            # 2. Low stock alert - only if crossing below threshold
            if item.min_quantity is not None and new_qty < item.min_quantity and old_qty >= item.min_quantity:
                print(
                    f"[EMAIL DEBUG] LOW STOCK ALERT: {item.name} at location {loc_id} dropped from {old_qty} to {new_qty} (min: {item.min_quantity})"
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
            print(f"[EMAIL DEBUG] Checking rare scan alert: looking for non-admin scans since {cutoff_date}")

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

            print(f"[EMAIL DEBUG] Query found non-admin scan: {last_non_admin_scan is not None}")

            if not last_non_admin_scan:
                print(
                    f"[EMAIL DEBUG] RARE SCAN ALERT: {item.name} hasn't been scanned by non-admin user in {user_alerts.rare_scan_days} days"
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
                print(f"[EMAIL DEBUG] Last non-admin scan was {days_since} days ago, no rare scan alert needed")

        print(f"[EMAIL DEBUG] Generated {len(alerts)} alerts: {alerts}")
        return alerts
