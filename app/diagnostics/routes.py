"""Client diagnostics API: POST /api/debug/report."""

from flask import request
from pydantic import ValidationError

from app import csrf
from app.shared.rate_limit import limiter
from app.shared.schema import ErrorResponse, SuccessResponse

from . import bp
from .schema import ClientDiagnosticsReport
from .service import record_diagnostics_report

RATE_LIMIT = "10 per minute"


@bp.post("/api/debug/report")
@csrf.exempt  # fired via background fetch() from unauthenticated pages, not a user-initiated form
@limiter.limit(RATE_LIMIT)
def report_client_diagnostics():
    ip = request.remote_addr or ""
    try:
        report = ClientDiagnosticsReport.model_validate(request.get_json(silent=True) or {})
    except ValidationError:
        return ErrorResponse(message="Invalid diagnostics payload.").model_dump(), 400

    record_diagnostics_report(report, ip=ip)
    return SuccessResponse().model_dump(), 202
