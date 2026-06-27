"""Pure stock-state policy helpers for item/location derived state."""

from dataclasses import dataclass

from app.alerts.constants import STOCK_ALERT_RANK, AlertSeverity, AlertType
from app.prediction.constants import MAX_EFFECTIVE_DAILY_USAGE, MIN_EFFECTIVE_DAILY_USAGE


@dataclass(frozen=True)
class StockStateEvaluation:
    """Forecasted and effective stock-alert result for one item/location state."""

    days_until_low: float | None
    days_until_stockout: float | None
    stock_status: AlertType | None
    forecast_status: AlertType | None
    effective_alert_type: AlertType | None
    effective_alert_rank: int
    effective_severity: AlertSeverity | None


def evaluate_stock_state(
    *,
    total_quantity: int,
    min_quantity: int,
    lead_time_days: int,
    prior_daily_usage: float,
    trend_per_day: float | None,
) -> StockStateEvaluation:
    """Return the full stock/forecast alert evaluation for one item/location row."""
    forecast_trend = -effective_daily_usage(trend_per_day, prior_daily_usage)
    days_until_low = days_to_threshold(total_quantity, forecast_trend, min_quantity, round_digits=1)
    days_until_stockout = days_to_threshold(total_quantity, forecast_trend, 0, round_digits=1)
    stock_status = current_stock_status(total_quantity, min_quantity)
    forecast_status = forecast_stock_status(days_until_low, days_until_stockout, lead_time_days)
    effective_alert_type = highest_priority_stock_alert(stock_status, forecast_status)
    return StockStateEvaluation(
        days_until_low=days_until_low,
        days_until_stockout=days_until_stockout,
        stock_status=stock_status,
        forecast_status=forecast_status,
        effective_alert_type=effective_alert_type,
        effective_alert_rank=STOCK_ALERT_RANK.get(effective_alert_type, 0) if effective_alert_type else 0,
        effective_severity=stock_alert_severity(
            effective_alert_type,
            total_quantity=total_quantity,
            min_quantity=min_quantity,
            lead_time_days=lead_time_days,
            days_until_low=days_until_low,
            days_until_stockout=days_until_stockout,
        ),
    )


def current_stock_status(total_quantity: int, min_quantity: int) -> AlertType | None:
    """Return the current non-forecast stock alert, if any."""
    if total_quantity <= 0:
        return AlertType.STOCKOUT
    if total_quantity < min_quantity:
        return AlertType.LOW_STOCK
    return None


def forecast_stock_status(
    days_until_low: float | None,
    days_until_stockout: float | None,
    lead_time_days: int,
) -> AlertType | None:
    """Return the forecast alert inside the configured lead-time window, if any."""
    if lead_time_days <= 0:
        return None
    if is_within_lead_time(days_until_stockout, lead_time_days):
        return AlertType.STOCKOUT_FORECAST
    if is_within_lead_time(days_until_low, lead_time_days):
        return AlertType.LOW_STOCK_FORECAST
    return None


def highest_priority_stock_alert(*alert_types: AlertType | None) -> AlertType | None:
    """Return the highest-priority stock alert from the provided candidates."""
    winner: AlertType | None = None
    winner_rank = -1
    for alert_type in alert_types:
        if alert_type is None:
            continue
        rank = STOCK_ALERT_RANK[alert_type]
        if rank > winner_rank:
            winner = alert_type
            winner_rank = rank
    return winner


def stock_alert_severity(
    alert_type: AlertType | None,
    *,
    total_quantity: int,
    min_quantity: int,
    lead_time_days: int,
    days_until_low: float | None,
    days_until_stockout: float | None,
) -> AlertSeverity | None:
    """Return the normalized alert severity for the winning stock alert."""
    if alert_type == AlertType.STOCKOUT:
        return AlertSeverity.CRITICAL
    if alert_type == AlertType.LOW_STOCK:
        return AlertSeverity.HIGH if total_quantity <= max(min_quantity // 2, 0) else AlertSeverity.WARNING
    if alert_type == AlertType.STOCKOUT_FORECAST:
        return forecast_alert_severity(days_until_stockout, lead_time_days)
    if alert_type == AlertType.LOW_STOCK_FORECAST:
        return forecast_alert_severity(days_until_low, lead_time_days)
    return None


def forecast_alert_severity(days_until_threshold: float | None, lead_time_days: int) -> AlertSeverity | None:
    """Return forecast severity for a threshold expected inside lead time."""
    if days_until_threshold is None or days_until_threshold > lead_time_days:
        return None
    if days_until_threshold <= 1:
        return AlertSeverity.CRITICAL
    if days_until_threshold <= 3:
        return AlertSeverity.HIGH
    if days_until_threshold <= 7:
        return AlertSeverity.WARNING
    return AlertSeverity.NOTICE


def effective_daily_usage(trend_per_day: float | None, prior_daily_usage: float) -> float:
    """Return bounded daily usage from a trained trend or fallback prior usage."""
    trend = trend_per_day if trend_per_day is not None else -float(prior_daily_usage or 0)
    usage = max(0.0, -float(trend))
    return min(max(usage, MIN_EFFECTIVE_DAILY_USAGE), MAX_EFFECTIVE_DAILY_USAGE)


def days_to_threshold(
    current_quantity: int,
    trend_per_day: float,
    threshold: float,
    *,
    round_digits: int | None = None,
) -> float | None:
    """Return days until a quantity threshold is reached, if usage trends down."""
    if current_quantity <= threshold:
        return 0.0
    if trend_per_day >= 0:
        return None
    value = (float(current_quantity) - threshold) / abs(trend_per_day)
    return round(value, round_digits) if round_digits is not None else value


def is_within_lead_time(days_until_threshold: float | None, lead_time_days: int) -> bool:
    """Return whether a threshold lands inside the configured lead-time window."""
    return days_until_threshold is not None and 0 <= days_until_threshold <= lead_time_days


def effective_lead_time_days(
    agency_lead_time_days: int | None,
    item_restock_delivery_days: int | None,
) -> int:
    """Item restock days override agency lead time when set."""
    value = item_restock_delivery_days if item_restock_delivery_days is not None else agency_lead_time_days
    return int(value or 0)
