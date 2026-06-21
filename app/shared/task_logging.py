"""Structured logging helpers for cron and CLI jobs."""

from collections.abc import Iterator
from contextlib import contextmanager
from time import perf_counter
from uuid import uuid4

from loguru import logger


@contextmanager
def logged_task(task_name: str, **context: object) -> Iterator[dict[str, object]]:
    """Log a task run with a stable run id, duration, and final result context."""
    task_run_id = uuid4().hex
    result: dict[str, object] = {}
    started_at = perf_counter()
    with logger.contextualize(task_name=task_name, task_run_id=task_run_id):
        logger.debug("Task started", extra=context)
        try:
            yield result
        except Exception as exc:
            logger.opt(exception=exc).error(
                "Task failed",
                extra=context | result | {"duration_ms": round((perf_counter() - started_at) * 1000)},
            )
            raise
        logger.info(
            "Task finished",
            extra=context | result | {"duration_ms": round((perf_counter() - started_at) * 1000)},
        )
