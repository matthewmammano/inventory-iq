"""Register shared HTML error pages for Flask."""

from dataclasses import dataclass

from flask import Flask, render_template, request, url_for
from flask_login import current_user
from flask_wtf.csrf import CSRFError
from loguru import logger

from app.shared.request_logging import log_missing_route


@dataclass(frozen=True, slots=True)
class ErrorPage:
    """Plain-language copy for one error screen, written for a volunteer at a kiosk."""

    code: int
    headline: str
    help_text: str


NOT_FOUND_PAGE = ErrorPage(404, "That page is not here", "If you scanned a barcode, scan it again. Otherwise tap Home to start over.")
PAGE_EXPIRED_PAGE = ErrorPage(400, "This page sat open too long", "Tap Home and start again. Nothing you did was lost.")
FORBIDDEN_PAGE = ErrorPage(403, "You do not have access to that", "Ask an admin to log in on this device first.")
RATE_LIMITED_PAGE = ErrorPage(429, "Too many tries", "Wait one minute, then try again.")
SERVER_ERROR_PAGE = ErrorPage(500, "Something broke on our end", "Your data is safe. Try again, and tell an admin if it keeps happening.")


def register_error_handlers(app: Flask) -> None:
    """Attach app-level error handlers."""

    def _home_url() -> str:
        """Where the error page's Home button goes; an agency is only known once signed in."""
        if current_user.is_authenticated:
            return url_for("guest.index", agency_id=current_user.id)
        return url_for("auth.login")

    def _err(page: ErrorPage) -> tuple[str, int]:
        return render_template("error.html", error_page=page, error_home_url=_home_url()), page.code

    def _log_denial(message: str, status_code: int) -> None:
        logger.warning(message, extra={"status_code": status_code, "method": request.method, "path": request.path, "endpoint": request.endpoint})

    @app.errorhandler(404)
    def not_found(_error):
        log_missing_route(request.path, request.method)
        return _err(NOT_FOUND_PAGE)

    @app.errorhandler(CSRFError)
    def csrf_error(_error):
        _log_denial("Request denied with CSRF error", PAGE_EXPIRED_PAGE.code)
        return _err(PAGE_EXPIRED_PAGE)

    @app.errorhandler(403)
    def forbidden(_error):
        _log_denial("Request denied with 403 access error", FORBIDDEN_PAGE.code)
        return _err(FORBIDDEN_PAGE)

    @app.errorhandler(429)
    def rate_limited(_error):
        _log_denial("Request denied with 429 rate limit error", RATE_LIMITED_PAGE.code)
        return _err(RATE_LIMITED_PAGE)

    @app.errorhandler(500)
    def internal(error):
        source_error = getattr(error, "original_exception", None) or error
        logger.opt(exception=source_error).error(
            "Request failed with an unhandled server error",
            extra={"status_code": SERVER_ERROR_PAGE.code, "method": request.method, "path": request.path, "endpoint": request.endpoint},
        )
        return _err(SERVER_ERROR_PAGE)
