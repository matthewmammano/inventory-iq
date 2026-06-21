"""Loguru logging configuration."""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from app.shared.file_retention import keep_newest_files

if TYPE_CHECKING:
    from loguru import Record

LOG_FILE_RETENTION_COUNT = 10

FILE_LOG_FORMAT = "{time:YYYY-MM-DD HH:mm:ss} | {level} | {extra[request_id]} | {extra[agency_id]} | " "{name}:{function}:{line} | {message}"
CONSOLE_LOG_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level}</level> | "
    "<cyan>{extra[request_id]}</cyan> | <cyan>{extra[agency_id]}</cyan> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
    "<level>{message}</level>"
)


def _patch_log_defaults(record: Record) -> None:
    extra = record["extra"]
    nested_extra = extra.pop("extra", None)
    if isinstance(nested_extra, dict):
        for key, value in nested_extra.items():
            extra.setdefault(key, value)

    extra["request_id"] = str(extra.get("request_id") or "_")
    agency_id = extra.get("agency_id")
    extra["agency_id"] = str(agency_id) if agency_id is not None else "_"


def setup_logging(
    *,
    debug: bool = False,
    json_logs: bool = False,
    log_file: str = "instance/logs/app.log",
) -> None:
    """Configure Loguru once for the current process."""
    logger.remove()
    logger.configure(patcher=_patch_log_defaults)

    level = "DEBUG" if debug else "INFO"
    _add_console_logging(level=level, debug=debug, json_logs=json_logs)
    _add_file_logging(level=level, log_file=log_file)


def _add_console_logging(*, level: str, debug: bool, json_logs: bool) -> None:
    if json_logs:
        logger.add(
            _write_json_log,
            level=level,
            backtrace=debug,
            diagnose=debug,
        )
        return

    logger.add(
        sys.stdout,
        level=level,
        format=CONSOLE_LOG_FORMAT,
        colorize=sys.stdout.isatty(),
        backtrace=debug,
        diagnose=debug,
    )


def _write_json_log(message: Any) -> None:
    payload = _build_json_log_payload(message.record)
    sys.stdout.write(f"{json.dumps(payload, default=str)}\n")
    sys.stdout.flush()


def _build_json_log_payload(record: Record) -> dict[str, Any]:
    payload = {
        "timestamp": record["time"].isoformat(),
        "level": record["level"].name,
        "logger": record["name"],
        "function": record["function"],
        "line": record["line"],
        "message": record["message"],
    }

    for key, value in record["extra"].items():
        if key not in payload:
            payload[key] = value

    exception = record.get("exception")
    if exception is not None:
        payload["exception"] = "".join(
            traceback.format_exception(
                exception.type,
                exception.value,
                exception.traceback,
            )
        ).rstrip()

    return payload


def _add_file_logging(*, level: str, log_file: str) -> None:
    try:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        logger.add(
            log_path,
            level=level,
            format=FILE_LOG_FORMAT,
            rotation="10 MB",
            retention=LOG_FILE_RETENTION_COUNT,
            compression="gz",
            backtrace=True,
            diagnose=False,
        )
        keep_newest_files(log_path.parent, "*.log*", LOG_FILE_RETENTION_COUNT)
    except OSError as exc:
        logger.warning(f"File logging disabled for this process: {exc}")
