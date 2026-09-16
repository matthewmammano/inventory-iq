"""Timezone conversion utilities."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from loguru import logger

DEFAULT_TIMEZONE = "UTC"


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
