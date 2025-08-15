"""Enhanced inventory prediction service with restock detection and time-weighted regression."""

# TODO RAINBOW: COMPREHENSIVE TESTING OF NEW BAYESIAN PREDICTION LOGIC
#
# CRITICAL: Test all new logic with fake ActionLogs before production deployment
#
# TEST SCENARIOS NEEDED:
# 1. PRIOR TESTING:
#    - Item with NO ML data, only prior_daily_usage → should use prior only
#    - Item with prior=0.5, verify fallback works correctly
#    - Item with invalid/null prior → should handle gracefully
#
# 2. POSTERIOR (ML + PRIOR) TESTING:
#    - Item with prior=0.3, ML confidence=0.7 → test Bayesian weighting
#    - Item with high ML confidence → should mostly ignore prior
#    - Item with low ML confidence → should rely more on prior
#
# 3. OPTION 1 LOGIC TESTING:
#    - Create fake COUNT sequences with known additions
#    - Test COUNT1 + additions >= COUNT2 filtering
#    - Verify periods with unknown restocks get skipped
#    - Test edge case: exactly COUNT1 + additions = COUNT2
#
# 4. FLOOR ROUNDING TESTING:
#    - Verify all predictions use math.floor() not int()
#    - Test: 15.9 days → 15 days (conservative)
#    - Test: 0.1 days → 0 days (immediate reorder)
#
# 5. POINT BORO DATA VALIDATION:
#    - Split historical data in half (train on first half)
#    - Use first half to get ML predictions + priors
#    - Test predictions against second half actual usage
#    - Check consistency: do predictions match reality?
#    - Measure prediction accuracy for high/medium/low confidence items
#
# IMPLEMENTATION:
# - Create test script with fake ActionLogs in controlled scenarios
# - Test each component: restock detection, period filtering, Bayesian math
# - Validate against Point Boro data split for real-world accuracy

import logging
import warnings
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import numpy as np
import math
from sklearn.linear_model import LinearRegression

warnings.filterwarnings("ignore")

logger = logging.getLogger(__name__)


class InventoryPredictor:
    """Predicts stockouts and low stock using linear regression on admin counts."""

    @staticmethod
    def get_usage_timeline(user_id: int, item_id: int, location_id: int) -> Dict:
        """Get usage data between admin counts."""
        from app.inventory.models import ActionLogs, OperationType

        # Get all admin counts for this item/location
        counts = (
            ActionLogs.query.filter(
                ActionLogs.user_id == user_id,
                ActionLogs.item_id == item_id,
                ActionLogs.to_location_id == location_id,
                ActionLogs.operation_type == OperationType.count,
                ActionLogs.admin_action == True
            )
            .order_by(ActionLogs.time_scanned.asc())
            .all()
        )

        if len(counts) < 2:
            return {"error": "Need 2+ admin counts for prediction"}

        periods = []
        for i in range(len(counts) - 1):
            start_count = counts[i]
            end_count = counts[i + 1]
            
            # Get all additions between these counts
            additions = ActionLogs.query.filter(
                ActionLogs.user_id == user_id,
                ActionLogs.item_id == item_id,
                ActionLogs.to_location_id == location_id,
                ActionLogs.from_location_id.is_(None),
                ActionLogs.time_scanned.between(start_count.time_scanned, end_count.time_scanned)
            ).all()
            
            total_additions = sum(add.quantity_delta for add in additions)
            expected_count = start_count.quantity_delta + total_additions
            
            # Use period only if COUNT1 + additions >= COUNT2
            if expected_count >= end_count.quantity_delta:
                actual_usage = expected_count - end_count.quantity_delta
                if actual_usage > 0:
                    days = (end_count.time_scanned - start_count.time_scanned).total_seconds() / 86400
                    if days > 0:
                        periods.append({
                            "days": days,
                            "actual_usage": actual_usage,
                            "daily_rate": actual_usage / days,
                            "start_time": start_count.time_scanned,
                            "end_time": end_count.time_scanned
                        })

        if not periods:
            return {"error": "No valid consumption periods found"}

        # Get current quantity from most recent count
        current_qty = counts[-1].quantity_delta if counts else 0

        return {
            "periods": periods,
            "current_qty": current_qty,
            "last_update": counts[-1].time_scanned if counts else None,
        }

    @staticmethod
    def _time_weighted_regression(periods: List[Dict], recency_weight: float = 2.0) -> Tuple[float, float]:
        """Perform time-weighted linear regression prioritizing recent data.

        Args:
            periods: List of consumption periods with daily_rate and timestamps
            recency_weight: Exponential weight factor for recent data (higher = more recent bias)

        Returns:
            Tuple of (predicted_daily_rate, confidence_score)
        """
        if len(periods) < 2:
            return 0.0, 0.0

        # Calculate days since each period ended (for weighting)
        now = datetime.now(timezone.utc)
        weights = []

        for period in periods:
            days_ago = (now - period["end_time"]).total_seconds() / 86400
            # Exponential decay: more recent data gets higher weight
            weight = np.exp(-days_ago / (365.25 / recency_weight))  # Half-life of ~6 months at weight=2
            weights.append(weight)

        weights = np.array(weights)
        weights = weights / weights.sum()  # Normalize to sum=1

        # TODO YELLOW: Upgrade from linear regression to seasonal-aware models
        # Current linear regression misses seasonal patterns. Consider:
        # 1. Sinusoidal regression: usage = a + b*time + c*sin(2π*time/365) + d*cos(2π*time/365)
        # 2. Random Forest: handles non-linear patterns, day-of-week effects automatically
        # 3. Prophet/seasonal decomposition: Facebook's time series forecasting
        # 4. Fourier transform features: capture weekly/monthly/quarterly cycles
        
        # Weighted linear regression (temporary until seasonal upgrade)
        X = np.array([[i] for i in range(len(periods))])
        y = np.array([p["daily_rate"] for p in periods])

        # Apply weights to regression
        model = LinearRegression()
        model.fit(X, y, sample_weight=weights)

        predicted_rate = model.predict([[len(periods)]])[0]
        confidence = model.score(X, y, sample_weight=weights)

        return max(0.0, predicted_rate), max(0.0, confidence)
    
    @staticmethod
    def _calculate_ml_confidence(periods: List[Dict], ml_r_squared: float) -> float:
        """Calculate ML prediction confidence based on data quantity and model fit."""
        if not periods:
            return 0.0
        
        # Base confidence from data quantity (5+ periods = full data confidence)
        data_confidence = min(len(periods) / 5.0, 1.0)
        
        # Model fit confidence (R² score)
        model_confidence = max(ml_r_squared, 0.0)
        
        # Data recency factor (reduce confidence for old data)
        if periods:
            latest_end = max(p["end_time"] for p in periods)
            days_since_latest = (datetime.now(timezone.utc) - latest_end).total_seconds() / 86400
            recency_factor = np.exp(-days_since_latest / 90)  # Half-life of ~3 months
        else:
            recency_factor = 0.0
        
        return data_confidence * model_confidence * recency_factor
    
    @staticmethod
    def _bayesian_prediction(ml_rate: float, ml_confidence: float, prior_rate: Optional[float]) -> Tuple[float, Dict[str, float]]:
        """Combine ML prediction with prior knowledge using Bayesian approach."""
        if prior_rate is None or prior_rate <= 0:
            # No prior knowledge - use ML only
            return ml_rate, {"ml_weight": 1.0, "prior_weight": 0.0, "ml_confidence": ml_confidence}
        
        if ml_confidence <= 0:
            # No ML data - use prior only  
            return prior_rate, {"ml_weight": 0.0, "prior_weight": 1.0, "ml_confidence": 0.0}
        
        # Bayesian combination
        ml_weight = ml_confidence
        prior_weight = 1.0 - ml_confidence
        
        final_rate = (ml_weight * ml_rate) + (prior_weight * prior_rate)
        
        confidence_breakdown = {
            "ml_weight": ml_weight,
            "prior_weight": prior_weight, 
            "ml_confidence": ml_confidence
        }
        
        return final_rate, confidence_breakdown

    @staticmethod
    def predict_stockout(timeline: Dict, prior_rate: Optional[float] = None, recency_weight: float = 2.0) -> Optional[Dict]:
        """Predict when quantity will hit 0 using Bayesian combination of ML and prior knowledge."""
        periods = timeline.get("periods", [])
        
        # Get ML prediction
        if len(periods) >= 2:
            ml_rate, ml_r_squared = InventoryPredictor._time_weighted_regression(periods, recency_weight)
            ml_confidence = InventoryPredictor._calculate_ml_confidence(periods, ml_r_squared)
        else:
            ml_rate, ml_confidence = 0.0, 0.0
        
        # Combine with prior using Bayesian approach
        final_rate, confidence_breakdown = InventoryPredictor._bayesian_prediction(ml_rate, ml_confidence, prior_rate)
        
        if final_rate <= 0:
            return None  # Stock not declining

        current_qty = timeline["current_qty"]
        days_until_zero = math.floor(current_qty / final_rate)

        return {
            "days_until_stockout": days_until_zero,
            "predicted_date": datetime.now(timezone.utc) + timedelta(days=days_until_zero),
            "daily_usage_rate": final_rate,
            "confidence_breakdown": confidence_breakdown,
        }

    @staticmethod
    def predict_low_stock(timeline: Dict, min_quantity: int, prior_rate: Optional[float] = None, recency_weight: float = 2.0) -> Optional[Dict]:
        """Predict when quantity will hit min_quantity threshold using Bayesian combination."""
        if not min_quantity:
            return None
            
        periods = timeline.get("periods", [])
        
        # Get ML prediction
        if len(periods) >= 2:
            ml_rate, ml_r_squared = InventoryPredictor._time_weighted_regression(periods, recency_weight)
            ml_confidence = InventoryPredictor._calculate_ml_confidence(periods, ml_r_squared)
        else:
            ml_rate, ml_confidence = 0.0, 0.0
        
        # Combine with prior using Bayesian approach
        final_rate, confidence_breakdown = InventoryPredictor._bayesian_prediction(ml_rate, ml_confidence, prior_rate)
        
        if final_rate <= 0:
            return None  # Stock not declining

        current_qty = timeline["current_qty"]
        if current_qty <= min_quantity:
            return {"already_low": True}

        days_until_low = math.floor((current_qty - min_quantity) / final_rate)

        return {
            "days_until_low_stock": days_until_low,
            "predicted_date": datetime.now(timezone.utc) + timedelta(days=days_until_low),
            "threshold": min_quantity,
            "daily_usage_rate": final_rate,
            "confidence_breakdown": confidence_breakdown,
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

        days_until_low = math.floor((current_total - min_quantity) / predicted_rate)

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

                return math.floor(current_total - estimated_actual_usage)

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
