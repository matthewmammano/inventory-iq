"""Type parsing utilities for HTTP request parameters.

Flask/web frameworks pass query params and form data as strings.
These utilities safely parse them to Python types with None fallback.
"""


def parse_optional_int(value: str | int | None) -> int | None:
    """Parse string to int, return None if invalid or missing.

    Handles query params like ?item_id=123 or ?item_id= or missing param.
    Also accepts int (already parsed) for flexibility.

    Examples:
        parse_optional_int("123")    → 123
        parse_optional_int("")       → None
        parse_optional_int(None)     → None
        parse_optional_int(456)      → 456
        parse_optional_int("abc")    → None

    Args:
        value: String, int, or None to parse

    Returns:
        Parsed integer or None if invalid/missing
    """
    if value is None or value == "":
        return None
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_optional_float(value: str | float | None) -> float | None:
    """Parse string to float, return None if invalid or missing.

    Args:
        value: String, float, or None to parse

    Returns:
        Parsed float or None if invalid/missing
    """
    if value is None or value == "":
        return None
    if isinstance(value, float):
        return value
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_bool(value: str | bool | None, default: bool = False) -> bool:
    """Parse string to bool with sensible defaults.

    Examples:
        parse_bool("True")   → True
        parse_bool("1")      → True
        parse_bool("yes")    → True
        parse_bool("False")  → False
        parse_bool(None)     → False (default)

    Args:
        value: String, bool, or None to parse
        default: Default value if None

    Returns:
        Parsed boolean
    """
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).lower() in ("true", "1", "yes", "on")
