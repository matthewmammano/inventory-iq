"""Inventory prediction service using admin recounts as ground truth."""

import logging
import warnings
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

import numpy as np
from sklearn.linear_model import LinearRegression

warnings.filterwarnings("ignore")

logger = logging.getLogger(__name__)


class InventoryPredictor:
    """Predicts stockouts and low stock using linear regression on admin recounts."""

    @staticmethod
    def get_usage_timeline(user_id: int, item_id: int, location_id: int) -> Dict:
        """Get usage data between admin recounts."""
        from app.inventory.models import ActionLogs

        # Get admin recounts chronologically
        recounts = (
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

        if len(recounts) < 2:
            return {"error": "Need 2+ admin recounts for prediction"}

        # Calculate actual usage between recounts
        periods = []
        for i in range(len(recounts) - 1):
            start, end = recounts[i], recounts[i + 1]

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
            "current_qty": recounts[-1].quantity_delta,
            "last_update": recounts[-1].time_scanned,
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

        # Get all admin recounts across all locations, grouped by date
        recounts = (
            ActionLogs.query.filter(
                ActionLogs.user_id == user_id,
                ActionLogs.item_id == item_id,
                ActionLogs.admin_action == True,
                ActionLogs.from_location_id.is_(None),
            )
            .order_by(ActionLogs.time_scanned.asc())
            .all()
        )

        if len(recounts) < 2:
            return {"error": "Need 2+ admin recounts for prediction"}

        # Group recounts by date to get total inventory snapshots
        from collections import defaultdict

        recount_dates = defaultdict(int)
        for recount in recounts:
            date_key = recount.time_scanned.date()
            recount_dates[date_key] += recount.quantity_delta

        if len(recount_dates) < 2:
            return {"error": "Need recounts on 2+ different dates"}

        # Sort dates and create periods
        sorted_dates = sorted(recount_dates.keys())
        periods = []

        for i in range(len(sorted_dates) - 1):
            start_date, end_date = sorted_dates[i], sorted_dates[i + 1]
            start_total = recount_dates[start_date]
            end_total = recount_dates[end_date]

            # Get all usage scans between these dates across all locations
            start_datetime = datetime.combine(start_date, datetime.min.time()).replace(tzinfo=timezone.utc)
            end_datetime = datetime.combine(end_date, datetime.min.time()).replace(tzinfo=timezone.utc)

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
            days = (end_date - start_date).days

            if days > 0 and actual_usage >= 0:
                periods.append(
                    {
                        "days": days,
                        "actual_usage": actual_usage,
                        "daily_rate": actual_usage / days,
                        "underreporting": actual_usage / max(scanned_usage, 1) if scanned_usage > 0 else 1.0,
                    }
                )

        current_total = recount_dates[sorted_dates[-1]]
        last_recount_date = sorted_dates[-1]

        return {"periods": periods, "current_qty": current_total, "last_update": last_recount_date}

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
