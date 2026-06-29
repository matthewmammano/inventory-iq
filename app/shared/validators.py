"""Shared validation helpers used by ORM models and Pydantic schemas."""

import re
import string
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from email_validator import EmailNotValidError, validate_email
from loguru import logger

PASSWORD_MIN_LENGTH = 10
PASSWORD_REQUIREMENTS_MESSAGE = "Password must be at least 10 characters and include a letter, number, and symbol."  # nosec B105 - user-facing validation copy


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
        logger.debug("Email validation rejected input", extra={"error": str(exc)})
        raise ValueError("Invalid email format") from exc
    validate_string_length(normalized, "email", max_length, allow_none=False, allow_empty=False)
    return normalized


def validate_timezone(value: str) -> str:
    """Validate timezone using zoneinfo (IANA names)."""
    value = validate_string_length(value, "timezone", 50, allow_none=False, allow_empty=False) or ""
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        logger.info("Timezone validation rejected input", extra={"timezone": value, "error": str(exc)})
        raise ValueError(f"Invalid timezone: {value}") from exc
    return value


def validate_hhmm_time(value: str | None, field_name: str, *, allow_none: bool = True) -> str | None:
    """Validate a 24-hour HH:MM local clock preference."""
    if value is None or value == "":
        if allow_none:
            return None
        raise ValueError(f"{field_name} cannot be empty")
    value = validate_string_length(value.strip(), field_name, 5, allow_none=False, allow_empty=False) or ""
    parts = value.split(":", maxsplit=1)
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        raise ValueError(f"{field_name} must use HH:MM")
    hour, minute = (int(part) for part in parts)
    if hour > 23 or minute > 59:
        raise ValueError(f"{field_name} must use HH:MM")
    return f"{hour:02d}:{minute:02d}"


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
    return validate_pin_length(value, 4)


def validate_pin_length(value: str, digits: int) -> str:
    """Validate fixed-length numeric PIN values."""
    if not value or not value.isdigit() or len(value) != digits:
        raise ValueError(f"PIN must be exactly {digits} digits")
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


def normalize_hex_color(value: str | None) -> str:
    """Validate and normalize #RRGGBB color strings."""
    if not value or not isinstance(value, str):
        raise TypeError("Color must be a string")
    normalized = value.strip()
    if not re.match(r"^#[0-9A-Fa-f]{6}$", normalized):
        raise ValueError("Color must be valid hex format: #rrggbb")
    return normalized.upper()


def validate_password_strength(password: str) -> str:
    """Validate password complexity used by account login."""
    if (
        len(password) < PASSWORD_MIN_LENGTH
        or not any(char.isalpha() for char in password)
        or not any(char.isdigit() for char in password)
        or not any(char in string.punctuation for char in password)
    ):
        raise ValueError(PASSWORD_REQUIREMENTS_MESSAGE)
    return password


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
