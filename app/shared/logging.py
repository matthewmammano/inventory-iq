"""Loguru logging configuration."""

import sys
from pathlib import Path
from typing import Any

from flask import has_request_context
from flask_login import current_user
from loguru import logger

from app.shared.file_retention import keep_newest_files

LOG_FILE_RETENTION_COUNT = 10

FILE_LOG_FORMAT = (
    "{time:YYYY-MM-DD HH:mm:ss} | {level} | "
    "{extra[agency_id]} | {name}:{function}:{line} | {message}"
)

CONSOLE_LOG_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level}</level> | "
    "<cyan>{extra[agency_id]}</cyan> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
    "<level>{message}</level>"
)


def _current_agency_id() -> str:
    if not has_request_context():
        return "_"
    try:
        if current_user.is_authenticated:
            return str(current_user.id)
    except RuntimeError:
        return "_"
    return "_"


def _add_agency_id(record: dict[str, Any]) -> None:
    extra = record["extra"]
    nested_extra = extra.get("extra")
    agency_id = extra.get("agency_id")
    if agency_id is None and isinstance(nested_extra, dict):
        agency_id = nested_extra.get("agency_id")
    extra["agency_id"] = str(agency_id) if agency_id is not None else _current_agency_id()


def setup_logging(*, debug: bool = False, log_file: str = "instance/logs/app.log") -> None:
    """Configure Loguru sinks. Call once at app startup."""
    logger.remove()
    logger.configure(patcher=_add_agency_id)  # type: ignore[arg-type]

    level = "DEBUG" if debug else "INFO"

    logger.add(
        sys.stderr,
        level=level,
        format=CONSOLE_LOG_FORMAT,
        colorize=True,
        backtrace=debug,
        diagnose=debug,
    )

    try:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        logger.add(
            log_path,
            level=level,
            format=FILE_LOG_FORMAT,
            colorize=False,
            rotation="10 MB",
            retention=LOG_FILE_RETENTION_COUNT,
            compression="gz",
            backtrace=True,
            diagnose=False,
        )
        keep_newest_files(log_path.parent, "*.log*", LOG_FILE_RETENTION_COUNT)
    except OSError as exc:
        logger.warning(f"File logging disabled for {log_file}: {exc}")
