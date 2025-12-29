# validation_helpers.py
"""
Validation helper functions for models.
Import this into models.py to keep validation logic organized.
"""

from loguru import logger


def validate_email_format(email: str) -> str:
    """Validate email format using email-validator library.

    Parameters
    ----------
    email : str
        Email address to validate

    Returns
    -------
    str
        Normalized email address

    Raises
    ------
    ValueError
        If email format is invalid
    """
    from email_validator import EmailNotValidError, validate_email

    try:
        # This validates format AND checks if domain exists
        valid_email = validate_email(email)
        return valid_email.email  # Returns normalized email
    except EmailNotValidError as e:
        logger.exception(f"Email validation failed for '{email}': {e}")
        raise ValueError("Invalid email format")


def validate_email_with_length(
    value: str | None, max_length: int, allow_none: bool = True
) -> str | None:
    """Validate email format and length (consolidated validation for all email fields)."""
    if value is None:
        if allow_none:
            return None
        raise ValueError("Email cannot be None")
    value = validate_email_format(value)
    validate_string_length(
        value, "email", max_length, allow_none=False, allow_empty=False
    )
    return value


def validate_timezone(value: str) -> str:
    """Validate timezone using pytz.

    Parameters
    ----------
    value : str
        Timezone string to validate

    Returns
    -------
    str
        Validated timezone string

    Raises
    ------
    ValueError
        If timezone is invalid
    """
    import pytz

    value = (
        validate_string_length(
            value, "timezone", 50, allow_none=False, allow_empty=False
        )
        or ""
    )

    try:
        pytz.timezone(value)
    except pytz.UnknownTimeZoneError as e:
        logger.exception(f"Timezone validation failed for '{value}': {e}")
        raise ValueError(f"Invalid timezone: {value}")

    return value


def validate_positive_integer(value, field_name, allow_none=True):
    """Validate that a value is a positive integer or None."""
    if value is None:
        if allow_none:
            return None
        logger.error(f"Validation failed: {field_name} cannot be None")
        raise ValueError(f"{field_name} cannot be None")
    if not isinstance(value, int) or value <= 0:
        logger.error(
            f"Validation failed: {field_name} must be a positive integer, got {type(value)} with value {value}"
        )
        raise ValueError(f"{field_name} must be a positive integer")
    return value


def validate_non_negative_integer(value, field_name, allow_none=True):
    """Validate that a value is a non-negative integer or None."""
    if value is None:
        if allow_none:
            return None
        logger.error(f"Validation failed: {field_name} cannot be None")
        raise ValueError(f"{field_name} cannot be None")
    if not isinstance(value, int) or value < 0:
        logger.error(
            f"Validation failed: {field_name} must be a non-negative integer, got {type(value)} with value {value}"
        )
        raise ValueError(f"{field_name} must be a non-negative integer")
    return value


def validate_string_length(
    value, field_name, max_length, allow_none=True, allow_empty=True
):
    """Validate string length constraints."""
    if value is None:
        if allow_none:
            return None
        logger.error(f"Validation failed: {field_name} cannot be None")
        raise ValueError(f"{field_name} cannot be None")
    if not isinstance(value, str):
        logger.error(
            f"Validation failed: {field_name} must be a string, got {type(value)}"
        )
        raise ValueError(f"{field_name} must be a string")
    if not allow_empty and not value.strip():
        logger.error(f"Validation failed: {field_name} cannot be empty")
        raise ValueError(f"{field_name} cannot be empty")
    if len(value) > max_length:
        logger.error(
            f"Validation failed: {field_name} cannot exceed {max_length} characters, got {len(value)}"
        )
        raise ValueError(f"{field_name} cannot exceed {max_length} characters")
    return value


def validate_image_url(value):
    """Validate image URL format and length. Allows HTTP/HTTPS URLs and local file paths."""
    if value:
        from urllib.parse import urlparse

        parsed = urlparse(value)

        # Check if it's a valid HTTP/HTTPS URL
        is_url = parsed.scheme and parsed.scheme in ("http", "https") and parsed.netloc

        # Check if it's a local file path (no scheme or file scheme)
        is_local_path = not parsed.scheme or parsed.scheme == "file"

        if not (is_url or is_local_path):
            logger.error(
                f"Image URL validation failed: '{value}' is not a valid URL or local file path"
            )
            raise ValueError("Image must be a valid URL or local file path")

        try:
            validate_string_length(value, "image", 1020)
        except ValueError as e:
            logger.exception(f"Image URL validation failed: {e}")
            raise
    return value


def validate_tag_id_type(tag_id):
    """Validate that a tag_id is an integer."""
    if not isinstance(tag_id, int):
        logger.error(
            f"Tag ID validation failed: expected integer, got {type(tag_id)} with value {tag_id}"
        )
        raise ValueError("Tag ID must be an integer")
    return tag_id
