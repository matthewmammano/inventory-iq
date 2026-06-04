"""Shared JSON formatter for application and Gunicorn logs."""

from typing import Any

from pythonjsonlogger.json import JsonFormatter


class AppJsonFormatter(JsonFormatter):
    """Normalize field names for log aggregation systems."""

    def process_log_record(self, log_data: dict[str, Any]) -> dict[str, Any]:
        _rename_field(log_data, "asctime", "timestamp")
        _rename_field(log_data, "levelname", "level")
        _rename_field(log_data, "name", "logger")
        _rename_field(log_data, "funcName", "function")
        _rename_field(log_data, "lineno", "line")
        return super().process_log_record(log_data)


def _rename_field(log_data: dict[str, Any], source: str, target: str) -> None:
    value = log_data.pop(source, None)
    if value is not None:
        log_data[target] = value
