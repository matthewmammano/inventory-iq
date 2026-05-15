"""Register shared HTML error pages for Flask."""

from flask import Flask, render_template, request
from loguru import logger


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
        if not request.path.startswith("/.well-known/"):
            logger.warning(f"404: {request.path}")
        return _err("Error", "Page Not Found", "The page you're looking for doesn't exist.", 404)

    @app.errorhandler(403)
    def forbidden(error):
        logger.warning(f"403: {request.path}")
        return _err("Error", "Access Denied", "You don't have permission to access this page.", 403)

    @app.errorhandler(500)
    def internal(error):
        logger.error(f"500: {error}")
        return _err(
            "Error", "System Error", "The system encountered a problem. Your data is safe.", 500
        )
