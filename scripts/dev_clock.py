"""Control local fake time for scheduler and alert QA.

Requires DEV_CLOCK_ENABLED=true. This writes instance/dev_clock.json; production
should leave fake time disabled.
"""

import argparse
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from app.shared.clock import CLOCK_FILE, utc_now


def main() -> None:
    """Parse CLI args and update the dev clock state file."""
    parser = argparse.ArgumentParser(description="Control instance/dev_clock.json")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    sub.add_parser("pause")
    sub.add_parser("resume")
    sub.add_parser("reset")

    set_cmd = sub.add_parser("set")
    set_cmd.add_argument("value", help='Example: "2026-05-07 08:00"')

    advance = sub.add_parser("advance")
    advance.add_argument("--hours", type=float, default=0)
    advance.add_argument("--days", type=float, default=0)

    speed = sub.add_parser("speed")
    speed.add_argument("multiplier", type=float)

    args = parser.parse_args()
    _run(args)


def _run(args: argparse.Namespace) -> None:
    match args.command:
        case "status":
            print(f"Dev clock now: {utc_now().isoformat()}")
            print(f"State file: {_read_state() or 'real time'}")
        case "set":
            _write_fixed(_parse_user_datetime(args.value))
        case "advance":
            _write_fixed(utc_now() + timedelta(hours=args.hours, days=args.days))
        case "speed":
            _write_scaled(args.multiplier)
        case "pause":
            _write_fixed(utc_now())
        case "resume":
            _write_scaled(1)
        case "reset":
            CLOCK_FILE.unlink(missing_ok=True)
            print("Dev clock reset to real time")


def _write_fixed(value: datetime) -> None:
    _write_state({"mode": "fixed", "fake_anchor": value.astimezone(UTC).isoformat()})
    print(f"Dev clock fixed at {utc_now().isoformat()}")


def _write_scaled(multiplier: float) -> None:
    if multiplier <= 0:
        raise ValueError("speed multiplier must be greater than 0")
    now = datetime.now(UTC)
    _write_state(
        {
            "mode": "scaled",
            "fake_anchor": utc_now().isoformat(),
            "real_anchor": now.isoformat(),
            "speed": multiplier,
        }
    )
    print(f"Dev clock running at {multiplier}x")


def _write_state(state: dict[str, Any]) -> None:
    CLOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    CLOCK_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _read_state() -> dict[str, Any] | None:
    if not CLOCK_FILE.exists():
        return None
    return json.loads(CLOCK_FILE.read_text(encoding="utf-8"))


def _parse_user_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.astimezone()
    return parsed.astimezone(UTC)


if __name__ == "__main__":
    main()
