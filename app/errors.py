"""Register shared HTML error pages for Flask."""

from flask import Flask, render_template, request
from loguru import logger

from app.shared.request_logging import log_missing_route


def register_error_handlers(app: Flask) -> None:
    """Attach app-level error handlers."""

    def _err(title: str, message: str, description: str, code: int) -> tuple[str, int]:
        return render_template(
            "error.html",
            error_title=title,
            error_message=message,
            error_description=description,
        ), code

    @app.errorhandler(404)
    def not_found(error):
        log_missing_route(request.path, request.method)
        return _err("Error", "Page Not Found", "The page you're looking for doesn't exist.", 404)

    @app.errorhandler(403)
    def forbidden(error):
        logger.warning(
            "Request denied with 403 access error",
            extra={"status_code": 403, "method": request.method, "path": request.path, "endpoint": request.endpoint},
        )
        return _err("Error", "Access Denied", "You don't have permission to access this page.", 403)

    @app.errorhandler(500)
    def internal(error):
        source_error = getattr(error, "original_exception", None) or error
        logger.opt(exception=source_error).error(
            "Request failed with an unhandled server error",
            extra={"status_code": 500, "method": request.method, "path": request.path, "endpoint": request.endpoint},
        )
        return _err("Error", "System Error", "The system encountered a problem. Your data is safe.", 500)
