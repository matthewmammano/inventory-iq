"""Display formatting for prediction values."""


def rounded_confidence_percent(value: float | int | None) -> int | None:
    """Round raw confidence to the nearest visible 10% bucket."""
    if value is None:
        return None
    clipped = max(0.0, min(float(value), 100.0))
    rounded = int(((clipped + 5) // 10) * 10)
    return max(10, rounded) if clipped > 0 else 0
