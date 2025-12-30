"""Error handlers for production-ready first aid squad application."""

from __future__ import annotations

from flask import Flask, render_template, request
from loguru import logger


def register_error_handlers(app: Flask) -> None:
    """
    Register error handlers with the Flask application.

    Parameters
    ----------
    app : Flask
        The Flask application instance to register handlers with

    Returns
    -------
    None
    """

    @app.errorhandler(404)
    def not_found_error(error: Exception) -> tuple[str, int]:
        """
        Handle 404 Not Found errors.

        Note: Function is accessed via Flask's errorhandler decorator system.

        Parameters
        ----------
        error : Exception
            The error that triggered this handler

        Returns
        -------
        tuple[str, int]
            Rendered error template with 404 status code
        """
        # Suppress Chrome DevTools auto-requests
        if not request.path.startswith("/.well-known/"):
            logger.warning(f"404 error: {error} | Path: {request.path}")
        return (
            render_template(
                "error.html",
                error_title="Error",
                error_message="Page Not Found",
                error_description="The page you're looking for doesn't exist.",
                show_back=True,
                show_home=True,
            ),
            404,
        )

    @app.errorhandler(500)
    def internal_error(error: Exception) -> tuple[str, int]:
        """
        Handle 500 Internal Server errors.

        Note: Function is accessed via Flask's errorhandler decorator system.

        Parameters
        ----------
        error : Exception
            The error that triggered this handler

        Returns
        -------
        tuple[str, int]
            Rendered error template with 500 status code
        """
        logger.error(f"500 error: {error}")
        logger.error(f"Full traceback:\n{repr(error)}", exc_info=True)
        return (
            render_template(
                "error.html",
                error_title="Error",
                error_message="System Error",
                error_description="The system encountered a problem. Your data is safe.",
                show_back=True,
                show_home=True,
            ),
            500,
        )

    @app.errorhandler(403)
    def forbidden_error(error: Exception) -> tuple[str, int]:
        """
        Handle 403 Forbidden errors.

        Note: Function is accessed via Flask's errorhandler decorator system.

        Parameters
        ----------
        error : Exception
            The error that triggered this handler

        Returns
        -------
        tuple[str, int]
            Rendered error template with 403 status code
        """
        logger.warning(f"403 error: {error}")
        return (
            render_template(
                "error.html",
                error_title="Error",
                error_message="Access Denied",
                error_description="You don't have permission to access this page.",
                show_back=True,
                show_home=True,
            ),
            403,
        )
