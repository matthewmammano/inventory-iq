"""Client diagnostics API: POST /api/debug/report."""

from threading import Lock

from cachetools import TTLCache
from flask import request
from pydantic import ValidationError

from app.shared.schema import ErrorResponse, SuccessResponse

from . import bp
from .schema import ClientDiagnosticsReport
from .service import record_diagnostics_report

RATE_LIMIT_PER_MINUTE = 10
_report_counts: TTLCache = TTLCache(maxsize=10_000, ttl=60)
_report_counts_lock = Lock()


@bp.post("/api/debug/report")
def report_client_diagnostics():
    ip = request.remote_addr or ""
    if _rate_limited(ip):
        return ErrorResponse(message="Too many diagnostics reports.").model_dump(), 429

    try:
        report = ClientDiagnosticsReport.model_validate(request.get_json(silent=True) or {})
    except ValidationError:
        return ErrorResponse(message="Invalid diagnostics payload.").model_dump(), 400

    record_diagnostics_report(report, ip=ip)
    return SuccessResponse().model_dump(), 202


def _rate_limited(ip: str) -> bool:
    with _report_counts_lock:
        count = _report_counts.get(ip, 0) + 1
        _report_counts[ip] = count
    return count > RATE_LIMIT_PER_MINUTE
