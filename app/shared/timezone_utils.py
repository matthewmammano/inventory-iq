"""Timezone conversion utilities."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from loguru import logger

DEFAULT_TIMEZONE = "UTC"
DISPLAY_DATETIME_FORMAT = "%Y-%m-%d %H:%M"
DISPLAY_DATE_FORMAT = "%Y-%m-%d"


def resolve_timezone(timezone: str | None) -> str:
    """Fall back to UTC when no per-agency timezone is set."""
    return timezone or DEFAULT_TIMEZONE


def convert_utc_to_local(utc_dt: datetime | None, timezone: str) -> datetime | None:
    if utc_dt is None:
        return None
    try:
        aware = utc_dt.replace(tzinfo=UTC) if utc_dt.tzinfo is None else utc_dt
        return aware.astimezone(ZoneInfo(timezone))
    except Exception as exc:
        logger.warning("Timezone conversion failed", extra={"timezone": timezone, "error": str(exc)})
        return utc_dt


def local_now(timezone: str | None, now: datetime) -> datetime:
    """Convert a UTC `now` (naive or aware) into local time for this timezone, defaulting to UTC."""
    aware = now.replace(tzinfo=UTC) if now.tzinfo is None else now
    return aware.astimezone(ZoneInfo(resolve_timezone(timezone)))


def utc_isoformat(value: datetime | None) -> str:
    """Stamp a stored UTC datetime for the browser, which reads an offsetless string as device-local."""
    if value is None:
        return ""
    aware = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return aware.isoformat()


def format_local_datetime(value: datetime | None, timezone: str, fallback: str = "") -> str:
    """Render a stored UTC datetime in the agency's timezone for server-rendered pages."""
    local = convert_utc_to_local(value, resolve_timezone(timezone))
    return local.strftime(DISPLAY_DATETIME_FORMAT) if local else fallback


def format_local_date(value: datetime | None, timezone: str, fallback: str = "") -> str:
    """Render a stored UTC datetime as a date in the agency's timezone."""
    local = convert_utc_to_local(value, resolve_timezone(timezone))
    return local.strftime(DISPLAY_DATE_FORMAT) if local else fallback
