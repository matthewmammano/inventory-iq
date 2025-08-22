# validation_helpers.py
"""
Validation helper functions for models.
Import this into models.py to keep validation logic organized.
"""

import logging


def validate_email_format(email):
    """Validate email format using email-validator library."""
    from email_validator import EmailNotValidError, validate_email

    try:
        # This validates format AND checks if domain exists
        valid_email = validate_email(email)
        return valid_email.email  # Returns normalized email
    except EmailNotValidError as e:
        logging.error(f"Email validation failed for '{email}': {e}")
        raise ValueError("Invalid email format")


def validate_timezone(value):
    """Validate timezone using pytz."""
    import pytz

    value = validate_string_length(value, "timezone", 50, allow_none=False, allow_empty=False)

    try:
        pytz.timezone(value)
    except pytz.UnknownTimeZoneError as e:
        logging.error(f"Timezone validation failed for '{value}': {e}")
        raise ValueError(f"Invalid timezone: {value}")

    return value


def validate_positive_integer(value, field_name, allow_none=True):
    """Validate that a value is a positive integer or None."""
    if value is None:
        if allow_none:
            return None
        logging.error(f"Validation failed: {field_name} cannot be None")
        raise ValueError(f"{field_name} cannot be None")
    if not isinstance(value, int) or value <= 0:
        logging.error(
            f"Validation failed: {field_name} must be a positive integer, got {type(value)} with value {value}"
        )
        raise ValueError(f"{field_name} must be a positive integer")
    return value


def validate_non_negative_integer(value, field_name, allow_none=True):
    """Validate that a value is a non-negative integer or None."""
    if value is None:
        if allow_none:
            return None
        logging.error(f"Validation failed: {field_name} cannot be None")
        raise ValueError(f"{field_name} cannot be None")
    if not isinstance(value, int) or value < 0:
        logging.error(
            f"Validation failed: {field_name} must be a non-negative integer, got {type(value)} with value {value}"
        )
        raise ValueError(f"{field_name} must be a non-negative integer")
    return value


def validate_string_length(value, field_name, max_length, allow_none=True, allow_empty=True):
    """Validate string length constraints."""
    if value is None:
        if allow_none:
            return None
        logging.error(f"Validation failed: {field_name} cannot be None")
        raise ValueError(f"{field_name} cannot be None")
    if not isinstance(value, str):
        logging.error(f"Validation failed: {field_name} must be a string, got {type(value)}")
        raise ValueError(f"{field_name} must be a string")
    if not allow_empty and not value.strip():
        logging.error(f"Validation failed: {field_name} cannot be empty")
        raise ValueError(f"{field_name} cannot be empty")
    if len(value) > max_length:
        logging.error(f"Validation failed: {field_name} cannot exceed {max_length} characters, got {len(value)}")
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
            logging.error(f"Image URL validation failed: '{value}' is not a valid URL or local file path")
            raise ValueError("Image must be a valid URL or local file path")

        try:
            validate_string_length(value, "image", 1020)
        except ValueError as e:
            logging.error(f"Image URL validation failed: {e}")
            raise
    return value


def validate_tag_id_type(tag_id):
    """Validate that a tag_id is an integer."""
    if not isinstance(tag_id, int):
        logging.error(f"Tag ID validation failed: expected integer, got {type(tag_id)} with value {tag_id}")
        raise ValueError("Tag ID must be an integer")
    return tag_id
