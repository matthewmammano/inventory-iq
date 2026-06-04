"""Shared validation helpers used by ORM models and Pydantic schemas."""

from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from email_validator import EmailNotValidError, validate_email
from loguru import logger


def validate_string_length(
    value: str | None,
    field_name: str,
    max_length: int,
    *,
    allow_none: bool = True,
    allow_empty: bool = True,
) -> str | None:
    """Validate string length constraints."""
    if value is None:
        if allow_none:
            return None
        raise ValueError(f"{field_name} cannot be None")
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    if not allow_empty and not value.strip():
        raise ValueError(f"{field_name} cannot be empty")
    if len(value) > max_length:
        raise ValueError(f"{field_name} cannot exceed {max_length} characters")
    return value


def validate_email_format(
    email: str | None,
    *,
    max_length: int = 255,
    allow_none: bool = False,
) -> str | None:
    """Validate and normalize email format."""
    if email is None:
        if allow_none:
            return None
        raise ValueError("Email cannot be None")
    try:
        normalized = validate_email(email).email
    except EmailNotValidError as exc:
        logger.exception(f"Email validation failed: {exc}")
        raise ValueError("Invalid email format") from exc
    validate_string_length(normalized, "email", max_length, allow_none=False, allow_empty=False)
    return normalized


def validate_timezone(value: str) -> str:
    """Validate timezone using zoneinfo (IANA names)."""
    value = validate_string_length(value, "timezone", 50, allow_none=False, allow_empty=False) or ""
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        logger.error(f"Timezone validation failed: {exc}")
        raise ValueError(f"Invalid timezone: {value}") from exc
    return value


def validate_image_url(value: str | None) -> str | None:
    """Validate image URL or local path."""
    if not value:
        return value
    parsed = urlparse(value)
    is_url = parsed.scheme in ("http", "https") and parsed.netloc
    is_local = not parsed.scheme or parsed.scheme == "file"
    if not (is_url or is_local):
        raise ValueError("Image must be a valid URL or local file path")
    return validate_string_length(value, "image", 1020, allow_none=False, allow_empty=False)


def validate_pin(value: str) -> str:
    """Validate PIN format (exactly 4 digits)."""
    if not value or not value.isdigit() or len(value) != 4:
        raise ValueError("PIN must be exactly 4 digits")
    return value


def validate_positive_integer(value: int | None, field_name: str, *, allow_none: bool = True) -> int | None:
    """Validate positive integer constraints."""
    if value is None:
        if allow_none:
            return None
        raise ValueError(f"{field_name} cannot be None")
    if not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
    return value


def validate_non_negative_integer(value: int | None, field_name: str, *, allow_none: bool = True) -> int | None:
    """Validate non-negative integer constraints."""
    if value is None:
        if allow_none:
            return None
        raise ValueError(f"{field_name} cannot be None")
    if not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return value


def parse_optional_int(value: int | str | None) -> int | None:
    """Parse a value that may be int, string, or None into int | None."""
    if value is None or value == "":
        return None
    if isinstance(value, int):
        return value
    try:
        return int(str(value).strip())
    except (ValueError, TypeError):
        return None
