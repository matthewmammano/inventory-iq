import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


def convert_utc_to_local(utc_datetime: datetime, user_timezone: str) -> datetime:
    """Convert UTC datetime to user's local timezone.

    Args:
        utc_datetime: DateTime object in UTC
        user_timezone: IANA timezone string (e.g., 'America/New_York')

    Returns:
        DateTime object converted to user's timezone, or original if conversion fails
    """
    if not utc_datetime:
        return None
    if not user_timezone:
        return utc_datetime

    try:
        # Ensure UTC timezone is set if not already
        utc_time = utc_datetime.replace(tzinfo=timezone.utc) if utc_datetime.tzinfo is None else utc_datetime
        # Convert to user's timezone
        local_tz = ZoneInfo(user_timezone)
        return utc_time.astimezone(local_tz)
    except Exception as e:
        # Fallback to UTC if timezone conversion fails
        logging.error(f"Timezone conversion failed from UTC to '{user_timezone}': {e}")
        return utc_datetime


def get_timezone_display_hint(user_timezone: str) -> str:
    """Get a display hint for the user's timezone.

    Args:
        user_timezone: IANA timezone string

    Returns:
        Human-readable timezone hint (e.g., 'EST', 'PDT')
    """
    if not user_timezone:
        return "UTC"

    try:
        # Get current timezone abbreviation
        now = datetime.now(ZoneInfo(user_timezone))
        return now.strftime("%Z")
    except Exception as e:
        logging.error(f"Timezone display hint generation failed for '{user_timezone}': {e}")
        return user_timezone.split("/")[-1]  # Fallback to city name
