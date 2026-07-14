"""Loguru logging configuration."""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path
from typing import TYPE_CHECKING, Any, TextIO

from flask import g, has_request_context, request, session
from flask_login import current_user
from loguru import logger

from app.shared.file_retention import keep_newest_files

if TYPE_CHECKING:
    from loguru import Record

LOG_FILE_RETENTION_COUNT = 10
LOG_FILE_MAX_BYTES = 10 * 1024 * 1024
CONTEXT_KEYS = frozenset(
    {
        "request_id",
        "agency_id",
        "agency_location_id",
        "admin",
        "task_name",
        "task_run_id",
    }
)

CONSOLE_LOG_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level}</level> | "
    "<cyan>{extra[agency_id_display]}</cyan> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
    "<level>{message}</level>"
)


def _patch_log_defaults(record: Record) -> None:
    extra = record["extra"]
    nested_extra = extra.pop("extra", None)
    if isinstance(nested_extra, dict):
        for key, value in nested_extra.items():
            extra.setdefault(key, value)

    for key, value in current_log_context().items():
        extra.setdefault(key, value)

    request_id = extra.get("request_id")
    agency_id = extra.get("agency_id")
    extra["request_id"] = request_id or None
    extra["agency_id"] = agency_id
    extra["request_id_display"] = str(request_id or "_")
    extra["agency_id_display"] = str(agency_id if agency_id is not None else "_")


def current_log_context() -> dict[str, object]:
    """Return request-scoped log context when a Flask request is active."""
    if not has_request_context():
        return {}

    view_args = request.view_args or {}
    return {
        "request_id": getattr(g, "request_id", None),
        "agency_id": _current_agency_id(),
        "agency_location_id": view_args.get("agency_location_id"),
        "admin": bool(session.get("admin")),
    }


def _current_agency_id() -> int | None:
    try:
        return current_user.id if current_user.is_authenticated else None
    except (AttributeError, RuntimeError):
        return None


def setup_logging(
    *,
    json_logs: bool = False,
    log_file: str = "instance/logs/app.jsonl",
) -> None:
    """Configure Loguru once for the current process."""
    logger.remove()
    logger.configure(patcher=_patch_log_defaults)

    level = "INFO"
    _add_console_logging(level=level, json_logs=json_logs)
    _add_file_logging(level=level, log_file=log_file)


def _add_console_logging(*, level: str, json_logs: bool) -> None:
    if json_logs:
        logger.add(
            _write_json_log,
            level=level,
            backtrace=False,
            diagnose=False,
        )
        return

    logger.add(
        sys.stdout,
        level=level,
        format=CONSOLE_LOG_FORMAT,
        colorize=sys.stdout.isatty(),
        backtrace=False,
        diagnose=False,
    )


def _write_json_log(message: Any) -> None:
    payload = _build_json_log_payload(message.record)
    sys.stdout.write(f"{json.dumps(payload, default=str)}\n")
    sys.stdout.flush()


def _build_json_log_payload(record: Record) -> dict[str, Any]:
    context, details = _split_log_extra(record["extra"])
    return {
        "message": record["message"],
        "timestamp": record["time"].isoformat(),
        "level": record["level"].name,
        "source": {"name": record["name"], "function": record["function"], "line": record["line"]},
        "process": {"id": record["process"].id, "name": record["process"].name},
        "context": context,
        "details": details,
        "exception": _json_exception(record["exception"]),
    }


def _split_log_extra(extra: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    context: dict[str, Any] = {}
    details: dict[str, Any] = {}
    for key, value in extra.items():
        if key.endswith("_display"):
            continue
        target = context if key in CONTEXT_KEYS else details
        target[key] = _json_value(value)
    return context, details


def _json_value(value: Any) -> Any:
    return None if value == "_" else value


def _json_exception(exception: Any) -> str | None:
    if exception is None:
        return None
    return "".join(traceback.format_exception(exception.type, exception.value, exception.traceback)).rstrip()


class JsonlFileSink:
    def __init__(self, log_path: Path) -> None:
        self.log_path = log_path
        self._file: TextIO = log_path.open("a", encoding="utf-8")

    def write(self, message: Any) -> None:
        self._rotate_if_needed()
        payload = _build_json_log_payload(message.record)
        self._file.write(f"{json.dumps(payload, default=str, ensure_ascii=False)}\n")
        self._file.flush()

    def stop(self) -> None:
        self._file.close()

    def _rotate_if_needed(self) -> None:
        if self.log_path.exists() and self.log_path.stat().st_size < LOG_FILE_MAX_BYTES:
            return
        self._file.close()
        rotated_path = self.log_path.with_name(f"{self.log_path.stem}.{self.log_path.stat().st_mtime_ns}{self.log_path.suffix}")
        self.log_path.rename(rotated_path)
        self._file = self.log_path.open("a", encoding="utf-8")


def _add_file_logging(*, level: str, log_file: str) -> None:
    try:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        logger.add(
            JsonlFileSink(log_path),
            level=level,
            backtrace=True,
            diagnose=False,
        )
        keep_newest_files(log_path.parent, "*.jsonl*", LOG_FILE_RETENTION_COUNT)
    except OSError as exc:
        logger.warning("File logging disabled for this process", extra={"error": str(exc)})
