"""Central time source with optional local development controls."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loguru import logger

from app.shared.config import settings

INSTANCE_DIR = Path(__file__).resolve().parents[2] / "instance"
CLOCK_FILE = INSTANCE_DIR / "dev_clock.json"


def utc_now() -> datetime:
    """Return current UTC time, using dev clock state only when explicitly enabled."""
    real_now = datetime.now(UTC)
    if not settings.dev_clock_enabled:
        return real_now
    return _fake_now(real_now) or real_now


def utc_now_naive() -> datetime:
    return utc_now().replace(tzinfo=None)


def current_speed() -> float:
    """Return fake-time speed multiplier for scaled dev clock mode."""
    if not settings.dev_clock_enabled:
        return 1.0

    state = _read_state()
    if not state or state.get("mode") != "scaled":
        return 1.0

    try:
        speed = float(state.get("speed", 1))
    except (TypeError, ValueError):
        return 1.0
    return max(speed, 1.0)


def _fake_now(real_now: datetime) -> datetime | None:
    state = _read_state()
    if not state:
        return None

    try:
        fake_anchor = _parse_iso(state["fake_anchor"])
        if state.get("mode") == "fixed":
            return fake_anchor

        real_anchor = _parse_iso(state["real_anchor"])
        speed = float(state.get("speed", 1))
        return fake_anchor + ((real_now - real_anchor) * speed)
    except (KeyError, TypeError, ValueError) as exc:
        logger.warning("Invalid dev clock state ignored: {}", exc)
        return None


def _read_state() -> dict[str, Any] | None:
    if not CLOCK_FILE.exists():
        return None
    try:
        return json.loads(CLOCK_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Unable to read dev clock file: {}", exc)
        return None


def _parse_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
