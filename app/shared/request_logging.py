"""Request logging helpers for lifecycle events and noisy probes."""

from pathlib import PurePosixPath
from time import perf_counter
from uuid import uuid4

from flask import Flask, g, request, session
from flask_login import current_user
from loguru import logger

REQUEST_ID_HEADER = "X-Request-ID"
SLOW_REQUEST_MS = 1000

SAFE_MISSING_ROUTE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
LOW_SIGNAL_MISSING_ROUTE_PATHS = frozenset(
    {
        "/.env",
        "/.env.production",
        "/.env.local",
        "/wp-config.php",
        "/xmlrpc.php",
        "/favicon.ico",
        "/robots.txt",
        "/ads.txt",
        "/apple-touch-icon.png",
        "/feed/",
    }
)
LOW_SIGNAL_MISSING_ROUTE_PREFIXES = (
    "/wp-",
    "/wp/",
    "/wordpress/",
    "/phpmyadmin/",
    "/phpMyAdmin/",
)
LOW_SIGNAL_MISSING_ROUTE_SUFFIXES = ("/wp-includes/wlwmanifest.xml",)
SUSPICIOUS_MISSING_ROUTE_PATHS = frozenset(
    {
        "/.git/config",
        "/.aws/credentials",
        "/server-status",
    }
)
SUSPICIOUS_MISSING_ROUTE_PREFIXES = (
    "/.git/",
    "/.svn/",
    "/cgi-bin/",
    "/vendor/phpunit/",
    "/_ignition/",
    "/actuator/",
)


def register_request_logging(app: Flask) -> None:
    """Attach structured request start, finish, and failure logs."""

    @app.before_request
    def _start_request_log() -> None:
        header_value = request.headers.get(REQUEST_ID_HEADER, "").strip()
        g.request_id = header_value[:64] or uuid4().hex
        g.request_started_at = perf_counter()

    @app.after_request
    def _finish_request_log(response):
        _log_request_finished(response)
        response.headers[REQUEST_ID_HEADER] = g.request_id
        return response

    @app.teardown_request
    def _log_request_exception(error: BaseException | None) -> None:
        if error is not None:
            logger.opt(exception=error).error(
                "Request failed",
                extra=_request_log_context() | {"duration_ms": _request_duration_ms()},
            )


def log_missing_route(path: str, method: str) -> None:
    """Log 404s at a level that matches their likely risk."""
    normalized_path = _normalize_path(path)
    if normalized_path.startswith("/.well-known/"):
        return

    normalized_method = method.upper()
    extra = {"path": normalized_path, "method": normalized_method}

    if _is_low_signal_missing_route(normalized_path):
        logger.debug("Missing route from low-signal probe", extra=extra)
        return

    if normalized_method not in SAFE_MISSING_ROUTE_METHODS:
        logger.warning("Missing route with unexpected method", extra=extra)
        return

    if _is_suspicious_missing_route(normalized_path):
        logger.warning("Missing route from suspicious probe", extra=extra)
        return

    logger.warning("Missing route", extra=extra)


def _log_request_finished(response) -> None:
    duration_ms = _request_duration_ms()
    extra = _request_log_context() | {
        "status_code": response.status_code,
        "duration_ms": duration_ms,
        "content_length": response.calculate_content_length(),
    }
    if response.status_code >= 400:
        logger.warning("Request finished with error status", extra=extra)
        return
    if duration_ms is not None and duration_ms >= SLOW_REQUEST_MS:
        logger.info("Slow request finished", extra=extra)
        return
    logger.debug("Request finished", extra=extra)


def _request_log_context() -> dict[str, object]:
    return {
        "request_id": g.request_id,
        "agency_id": current_user.id if current_user.is_authenticated else None,
        "method": request.method,
        "path": request.path,
        "endpoint": request.endpoint,
        "squad": (request.view_args or {}).get("squad"),
        "admin_session": bool(session.get("admin")),
    }


def _request_duration_ms() -> int | None:
    started_at = getattr(g, "request_started_at", None)
    if started_at is None:
        return None
    return round((perf_counter() - started_at) * 1000)


def _normalize_path(path: str) -> str:
    normalized_path = path.strip() or "/"
    return normalized_path if normalized_path.startswith("/") else f"/{normalized_path}"


def _is_low_signal_missing_route(path: str) -> bool:
    return (
        path in LOW_SIGNAL_MISSING_ROUTE_PATHS
        or path.startswith(LOW_SIGNAL_MISSING_ROUTE_PREFIXES)
        or path.endswith(LOW_SIGNAL_MISSING_ROUTE_SUFFIXES)
        or _is_root_php_probe(path)
    )


def _is_root_php_probe(path: str) -> bool:
    parsed_path = PurePosixPath(path)
    return len(parsed_path.parts) == 2 and parsed_path.suffix.lower() == ".php"


def _is_suspicious_missing_route(path: str) -> bool:
    return path in SUSPICIOUS_MISSING_ROUTE_PATHS or path.startswith(SUSPICIOUS_MISSING_ROUTE_PREFIXES)
