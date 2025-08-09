"""Inventory prediction service using admin counts as ground truth."""

import logging
import warnings
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

import numpy as np
from sklearn.linear_model import LinearRegression

warnings.filterwarnings("ignore")

logger = logging.getLogger(__name__)


class InventoryPredictor:
    """Predicts stockouts and low stock using linear regression on admin counts."""

    @staticmethod
    def get_usage_timeline(user_id: int, item_id: int, location_id: int) -> Dict:
        """Get usage data between admin counts."""
        from app.inventory.models import ActionLogs

        # Get admin counts chronologically
        counts = (
            ActionLogs.query.filter(
                ActionLogs.user_id == user_id,
                ActionLogs.item_id == item_id,
                ActionLogs.to_location_id == location_id,
                ActionLogs.admin_action == True,
                ActionLogs.from_location_id.is_(None),
            )
            .order_by(ActionLogs.time_scanned.asc())
            .all()
        )

        if len(counts) < 2:
            return {"error": "Need 2+ admin counts for prediction"}

        # Calculate actual usage between counts
        periods = []
        for i in range(len(counts) - 1):
            start, end = counts[i], counts[i + 1]

            # User scans leaving this location
            scans = ActionLogs.query.filter(
                ActionLogs.user_id == user_id,
                ActionLogs.item_id == item_id,
                ActionLogs.from_location_id == location_id,
                ActionLogs.admin_action == False,
                ActionLogs.time_scanned.between(start.time_scanned, end.time_scanned),
            ).all()

            actual_usage = start.quantity_delta - end.quantity_delta
            scanned_usage = sum(log.quantity_delta for log in scans)
            days = (end.time_scanned - start.time_scanned).days

            if days > 0:
                periods.append(
                    {
                        "days": days,
                        "actual_usage": actual_usage,
                        "daily_rate": actual_usage / days,
                        "underreporting": actual_usage / max(scanned_usage, 1),
                    }
                )

        return {
            "periods": periods,
            "current_qty": counts[-1].quantity_delta,
            "last_update": counts[-1].time_scanned,
        }

    @staticmethod
    def predict_stockout(timeline: Dict) -> Optional[Dict]:
        """Predict when quantity will hit 0."""
        if timeline.get("error") or len(timeline.get("periods", [])) < 2:
            return None

        periods = timeline["periods"]
        X = np.array([[i] for i in range(len(periods))])
        y = np.array([p["daily_rate"] for p in periods])

        model = LinearRegression().fit(X, y)
        predicted_rate = model.predict([[len(periods)]])[0]

        if predicted_rate <= 0:
            return None  # Stock not declining

        current_qty = timeline["current_qty"]
        days_until_zero = int(current_qty / predicted_rate)

        return {
            "days_until_stockout": days_until_zero,
            "predicted_date": datetime.now(timezone.utc) + timedelta(days=days_until_zero),
            "daily_usage_rate": predicted_rate,
            "confidence": model.score(X, y),
        }

    @staticmethod
    def predict_low_stock(timeline: Dict, min_quantity: int) -> Optional[Dict]:
        """Predict when quantity will hit min_quantity threshold."""
        if timeline.get("error") or len(timeline.get("periods", [])) < 2 or not min_quantity:
            return None

        periods = timeline["periods"]
        X = np.array([[i] for i in range(len(periods))])
        y = np.array([p["daily_rate"] for p in periods])

        model = LinearRegression().fit(X, y)
        predicted_rate = model.predict([[len(periods)]])[0]

        if predicted_rate <= 0:
            return None  # Stock not declining

        current_qty = timeline["current_qty"]
        if current_qty <= min_quantity:
            return {"already_low": True}

        days_until_low = int((current_qty - min_quantity) / predicted_rate)

        return {
            "days_until_low_stock": days_until_low,
            "predicted_date": datetime.now(timezone.utc) + timedelta(days=days_until_low),
            "threshold": min_quantity,
            "daily_usage_rate": predicted_rate,
            "confidence": model.score(X, y),
        }

    @staticmethod
    def will_stockout_in_days(user_id: int, item_id: int, location_id: int, days_ahead: int) -> bool:
        """Check if stockout will occur within specified days."""
        timeline = InventoryPredictor.get_usage_timeline(user_id, item_id, location_id)
        prediction = InventoryPredictor.predict_stockout(timeline)
        return prediction and prediction["days_until_stockout"] <= days_ahead

    @staticmethod
    def will_be_low_in_days(user_id: int, item_id: int, location_id: int, min_qty: int, days_ahead: int) -> bool:
        """Check if low stock will occur within specified days."""
        timeline = InventoryPredictor.get_usage_timeline(user_id, item_id, location_id)
        prediction = InventoryPredictor.predict_low_stock(timeline, min_qty)
        return prediction and not prediction.get("already_low") and prediction["days_until_low_stock"] <= days_ahead

    @staticmethod
    def get_total_usage_timeline(user_id: int, item_id: int) -> Dict:
        """Get usage data aggregated across ALL locations for an item."""
        from app.inventory.models import ActionLogs

        # Get all admin counts with full datetime precision - time matters!
        counts = (
            ActionLogs.query.filter(
                ActionLogs.user_id == user_id,
                ActionLogs.item_id == item_id,
                ActionLogs.admin_action == True,
                ActionLogs.from_location_id.is_(None),
            )
            .order_by(ActionLogs.time_scanned.asc())
            .all()
        )

        if len(counts) < 2:
            return {"error": "Need 2+ admin counts for prediction"}

        # Group by date but only keep LATEST count per location per date
        from collections import defaultdict

        count_dates = defaultdict(int)
        count_datetimes = defaultdict(list)
        latest_per_location_per_date = {}  # (date, location) -> count

        # First pass: find latest count per location per date
        for count in counts:
            date_key = count.time_scanned.date()
            location_id = count.to_location_id
            key = (date_key, location_id)

            if (
                key not in latest_per_location_per_date
                or count.time_scanned > latest_per_location_per_date[key].time_scanned
            ):
                latest_per_location_per_date[key] = count

        # Second pass: aggregate using only latest counts per location per date
        for count in latest_per_location_per_date.values():
            date_key = count.time_scanned.date()
            count_dates[date_key] += count.quantity_delta
            count_datetimes[date_key].append(count)

        if len(count_dates) < 2:
            return {"error": "Need counts on 2+ different dates"}

        # Sort dates and create periods
        sorted_dates = sorted(count_dates.keys())
        periods = []

        for i in range(len(sorted_dates) - 1):
            start_date, end_date = sorted_dates[i], sorted_dates[i + 1]
            start_total = count_dates[start_date]
            end_total = count_dates[end_date]

            # Use actual datetime precision for period calculations
            start_counts = count_datetimes[start_date]
            end_counts = count_datetimes[end_date]

            # Use latest count time from start date and earliest from end date
            start_datetime = max(r.time_scanned for r in start_counts)
            end_datetime = min(r.time_scanned for r in end_counts)

            total_scanned_usage = (
                ActionLogs.query.filter(
                    ActionLogs.user_id == user_id,
                    ActionLogs.item_id == item_id,
                    ActionLogs.admin_action == False,
                    ActionLogs.from_location_id is not None,  # Taking from locations
                    ActionLogs.to_location_id is None,  # Not transferring
                    ActionLogs.time_scanned.between(start_datetime, end_datetime),
                )
                .with_entities(ActionLogs.quantity_delta)
                .all()
            )

            actual_usage = start_total - end_total
            scanned_usage = sum(scan.quantity_delta for scan in total_scanned_usage)
            # Use precise datetime difference for accurate daily rates
            time_diff = end_datetime - start_datetime
            days = time_diff.total_seconds() / 86400  # Convert to fractional days

            if days > 0 and actual_usage >= 0:
                periods.append(
                    {
                        "days": days,
                        "actual_usage": actual_usage,
                        "daily_rate": actual_usage / days,
                        "underreporting": actual_usage / max(scanned_usage, 1) if scanned_usage > 0 else 1.0,
                    }
                )

        current_total = count_dates[sorted_dates[-1]]
        last_count_date = sorted_dates[-1]

        return {"periods": periods, "current_qty": current_total, "last_update": last_count_date}

    @staticmethod
    def predict_total_low_stock(user_id: int, item_id: int, min_quantity: int) -> Optional[Dict]:
        """Predict when TOTAL inventory will hit minimum threshold."""
        timeline = InventoryPredictor.get_total_usage_timeline(user_id, item_id)

        if timeline.get("error") or len(timeline.get("periods", [])) < 2:
            return None

        periods = timeline["periods"]
        X = np.array([[i] for i in range(len(periods))])
        y = np.array([p["daily_rate"] for p in periods])

        model = LinearRegression().fit(X, y)
        predicted_rate = model.predict([[len(periods)]])[0]

        if predicted_rate <= 0:
            return None  # Stock not declining

        current_total = timeline["current_qty"]
        if current_total <= min_quantity:
            return {"already_low": True, "current_total": current_total}

        days_until_low = int((current_total - min_quantity) / predicted_rate)

        return {
            "days_until_low_stock": days_until_low,
            "predicted_date": datetime.now(timezone.utc) + timedelta(days=days_until_low),
            "threshold": min_quantity,
            "daily_usage_rate": predicted_rate,
            "confidence": model.score(X, y),
            "current_total": current_total,
        }

    @staticmethod
    def get_current_total_for_item(user_id: int, item_id: int) -> int:
        """Get current total by starting with latest counts and applying subsequent transfers."""
        from app.inventory.models import ActionLogs

        # Get most recent admin count for each location
        latest_counts = {}  # location_id -> (datetime, quantity)

        counts = ActionLogs.query.filter(
            ActionLogs.user_id == user_id,
            ActionLogs.item_id == item_id,
            ActionLogs.admin_action == True,
            ActionLogs.from_location_id.is_(None),
        ).all()

        if not counts:
            return 0

        # Find most recent count per location
        for count in counts:
            location_id = count.to_location_id
            if location_id not in latest_counts or count.time_scanned > latest_counts[location_id][0]:
                latest_counts[location_id] = (count.time_scanned, count.quantity_delta)

        # Start with quantities from latest counts
        current_quantities = {}  # location_id -> current_quantity
        earliest_count_time = None

        for location_id, (count_time, quantity) in latest_counts.items():
            current_quantities[location_id] = quantity
            if earliest_count_time is None or count_time < earliest_count_time:
                earliest_count_time = count_time

        # Apply ALL transfers/takes that happened AFTER the earliest of the latest counts
        if earliest_count_time:
            subsequent_actions = (
                ActionLogs.query.filter(
                    ActionLogs.user_id == user_id,
                    ActionLogs.item_id == item_id,
                    ActionLogs.time_scanned > earliest_count_time,
                    ActionLogs.admin_action == False,  # Only guest/user actions
                )
                .order_by(ActionLogs.time_scanned.asc())
                .all()
            )

            # Apply each action chronologically
            for action in subsequent_actions:
                # Taking from location (reduce quantity)
                if action.from_location_id and action.to_location_id is None:
                    if action.from_location_id not in current_quantities:
                        current_quantities[action.from_location_id] = 0
                    current_quantities[action.from_location_id] -= action.quantity_delta

                # Transfer between locations
                elif action.from_location_id and action.to_location_id:
                    if action.from_location_id not in current_quantities:
                        current_quantities[action.from_location_id] = 0
                    if action.to_location_id not in current_quantities:
                        current_quantities[action.to_location_id] = 0

                    current_quantities[action.from_location_id] -= action.quantity_delta
                    current_quantities[action.to_location_id] += action.quantity_delta

        # Return total across all locations
        return sum(current_quantities.values())

    @staticmethod
    def get_estimated_total_for_item(user_id: int, item_id: int) -> int:
        """Get estimated current total accounting for underreporting."""
        current_total = InventoryPredictor.get_current_total_for_item(user_id, item_id)

        if current_total == 0:
            return 0

        # Calculate underreporting ratio from timeline data
        timeline = InventoryPredictor.get_total_usage_timeline(user_id, item_id)

        if timeline.get("error") or not timeline.get("periods"):
            return current_total  # No adjustment possible

        # Get average underreporting ratio from periods
        periods = timeline["periods"]
        underreporting_ratios = [p.get("underreporting", 1.0) for p in periods if p.get("underreporting")]

        if underreporting_ratios:
            avg_underreporting = sum(underreporting_ratios) / len(underreporting_ratios)
            # Estimate unaccounted usage since last count
            from app.inventory.models import ActionLogs

            # Get most recent admin count date
            latest_count = (
                ActionLogs.query.filter(
                    ActionLogs.user_id == user_id,
                    ActionLogs.item_id == item_id,
                    ActionLogs.admin_action == True,
                    ActionLogs.from_location_id.is_(None),
                )
                .order_by(ActionLogs.time_scanned.desc())
                .first()
            )

            if latest_count:
                # Get guest usage since last count
                guest_usage = ActionLogs.query.filter(
                    ActionLogs.user_id == user_id,
                    ActionLogs.item_id == item_id,
                    ActionLogs.admin_action == False,
                    ActionLogs.from_location_id.is_not(None),
                    ActionLogs.to_location_id.is_(None),
                    ActionLogs.time_scanned > latest_count.time_scanned,
                ).all()

                reported_usage = sum(log.quantity_delta for log in guest_usage)
                estimated_actual_usage = reported_usage * avg_underreporting

                return int(current_total - estimated_actual_usage)

        return current_total

    @staticmethod
    def recalculate_all_quantities(user_id: int):
        """Recalculate item_location_quantities from admin counts."""
        from app import db
        from app.inventory.models import ActionLogs, ItemLocationQuantities

        # Clear existing quantities for this user
        ItemLocationQuantities.query.filter_by(user_id=user_id).delete()

        # Get all admin counts
        admin_counts = ActionLogs.query.filter(
            ActionLogs.user_id == user_id,
            ActionLogs.admin_action == True,
            ActionLogs.from_location_id.is_(None),
        ).all()

        # Group by item and location, keep most recent
        latest_quantities = {}  # (item_id, location_id) -> quantity

        for count in admin_counts:
            key = (count.item_id, count.to_location_id)
            if key not in latest_quantities:
                latest_quantities[key] = (count.time_scanned, count.quantity_delta)
            else:
                existing_time, existing_qty = latest_quantities[key]
                if count.time_scanned > existing_time:
                    latest_quantities[key] = (count.time_scanned, count.quantity_delta)

        # Create new ItemLocationQuantities records
        for (item_id, location_id), (_, quantity) in latest_quantities.items():
            new_qty = ItemLocationQuantities(
                user_id=user_id, item_id=item_id, location_id=location_id, quantity=quantity
            )
            db.session.add(new_qty)

        db.session.commit()
