"""Loguru logging configuration."""

import contextlib
import sys
from pathlib import Path

from flask import has_request_context
from flask_login import current_user
from loguru import logger

from app.shared.file_retention import keep_newest_files

LOG_FILE_RETENTION_COUNT = 10

FILE_LOG_FORMAT = "{time:YYYY-MM-DD HH:mm:ss} | {level} | {extra[agency_id]} | {name}:{function}:{line} | {message}"
CONSOLE_LOG_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level}</level> | "
    "<cyan>{extra[agency_id]}</cyan> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
    "<level>{message}</level>"
)


def _patch_agency_id(record: dict) -> None:  # type: ignore[type-arg]
    extra = record["extra"]
    agency_id = extra.get("agency_id")
    if agency_id is None and has_request_context():
        # contextlib.suppress(X) is just shorthand for try/except X: pass
        # It silently ignores the given exception type and moves on
        with contextlib.suppress(RuntimeError):
            agency_id = current_user.id if current_user.is_authenticated else None
    extra["agency_id"] = str(agency_id) if agency_id is not None else "_"


def setup_logging(*, debug: bool = False, log_file: str = "instance/logs/app.log") -> None:
    """Configure Loguru. Call once at startup."""
    logger.remove()
    logger.configure(patcher=_patch_agency_id)  # type: ignore[arg-type]

    level = "DEBUG" if debug else "INFO"

    # INFO/WARNING → stdout
    logger.add(  # type: ignore[call-overload]
        sys.stdout,
        level=level,
        format=CONSOLE_LOG_FORMAT,
        filter=lambda r: r["level"].no < 40,
        colorize=sys.stdout.isatty(),
        backtrace=debug,
        diagnose=debug,
    )

    # ERROR+ → stderr
    logger.add(  # type: ignore[call-overload]
        sys.stderr,
        level="ERROR",
        format=CONSOLE_LOG_FORMAT,
        colorize=sys.stderr.isatty(),
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
            rotation="10 MB",
            retention=LOG_FILE_RETENTION_COUNT,
            compression="gz",
            backtrace=True,
            diagnose=False,
        )
        keep_newest_files(log_path.parent, "*.log*", LOG_FILE_RETENTION_COUNT)
    except OSError as exc:
        logger.warning(f"File logging disabled: {exc}")
