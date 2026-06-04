"""Request logging helpers for missing routes and noisy probes."""

from loguru import logger

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
    }
)
LOW_SIGNAL_MISSING_ROUTE_PREFIXES = (
    "/wp-",
    "/wordpress/",
    "/phpmyadmin/",
    "/phpMyAdmin/",
)
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


def _normalize_path(path: str) -> str:
    normalized_path = path.strip() or "/"
    return normalized_path if normalized_path.startswith("/") else f"/{normalized_path}"


def _is_low_signal_missing_route(path: str) -> bool:
    return path in LOW_SIGNAL_MISSING_ROUTE_PATHS or path.startswith(LOW_SIGNAL_MISSING_ROUTE_PREFIXES)


def _is_suspicious_missing_route(path: str) -> bool:
    return path in SUSPICIOUS_MISSING_ROUTE_PATHS or path.startswith(SUSPICIOUS_MISSING_ROUTE_PREFIXES)
