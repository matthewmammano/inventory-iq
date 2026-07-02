"""Display formatting for prediction values."""


def format_usage_rate(rate_per_day: float | int | None) -> str | None:
    """Format a daily usage rate into the most readable time unit."""
    if rate_per_day is None:
        return None

    daily_rate = abs(float(rate_per_day))
    options = [
        ("day", daily_rate),
        ("week", daily_rate * 7),
        ("month", daily_rate * 30),
        ("year", daily_rate * 365),
    ]
    unit, value = next(((unit, value) for unit, value in options if value >= 1), options[-1])
    return f"{_format_usage_value(value)} per {unit}"


def rounded_confidence_percent(value: float | int | None) -> int | None:
    """Round raw confidence to the nearest visible 10% bucket."""
    if value is None:
        return None
    clipped = max(0.0, min(float(value), 100.0))
    rounded = int(((clipped + 5) // 10) * 10)
    return max(10, rounded) if clipped > 0 else 0


def _format_usage_value(value: float) -> str:
    return f"{value:.0f}" if value >= 10 else f"{value:.1f}"
