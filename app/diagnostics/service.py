"""Logging service for client diagnostics reports."""

from loguru import logger

from app.diagnostics.geo_lookup import lookup_geo
from app.diagnostics.schema import ClientDiagnosticsReport


def record_diagnostics_report(report: ClientDiagnosticsReport, *, ip: str) -> None:
    """Log one structured event combining the client payload with server-side geo context."""
    geo = lookup_geo(ip) if ip else None
    client_diagnostics = report.model_dump(exclude={"correlated_request_id"}) | {
        "ip": ip or None,
        "country": geo.country if geo else None,
        "city": geo.city if geo else None,
    }
    logger.info(
        "Client diagnostics received",
        extra={
            "correlated_request_id": report.correlated_request_id,
            "client_diagnostics": client_diagnostics,
        },
    )
