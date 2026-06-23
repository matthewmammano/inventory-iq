"""Timezone conversion utilities."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from loguru import logger


def convert_utc_to_local(utc_dt: datetime | None, timezone: str) -> datetime | None:
    if utc_dt is None:
        return None
    try:
        aware = utc_dt.replace(tzinfo=UTC) if utc_dt.tzinfo is None else utc_dt
        return aware.astimezone(ZoneInfo(timezone))
    except Exception as exc:
        logger.warning("Timezone conversion failed", extra={"timezone": timezone, "error": str(exc)})
        return utc_dt


def get_timezone_hint(timezone: str) -> str:
    if not timezone:
        return "UTC"
    try:
        return datetime.now(ZoneInfo(timezone)).strftime("%Z")
    except Exception:
        return timezone.split("/")[-1]
