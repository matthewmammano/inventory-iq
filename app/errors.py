"""
Error handlers for production-ready first aid squad application.
"""

from flask import render_template


def register_error_handlers(app):
    """Register error handlers with the Flask app."""

    @app.errorhandler(404)
    def not_found_error(error):
        app.logger.warning(f"404 error: {error}")
        return render_template(
            "error.html",
            error_title="Error",
            error_message="Page Not Found",
            error_description="The page you're looking for doesn't exist.",
            show_back=True,
            show_home=True,
        ), 404

    @app.errorhandler(500)
    def internal_error(error):
        app.logger.error(f"500 error: {error}")
        return render_template(
            "error.html",
            error_title="Error",
            error_message="System Error",
            error_description="The system encountered a problem. Your data is safe.",
            show_back=True,
            show_home=True,
        ), 500

    @app.errorhandler(403)
    def forbidden_error(error):
        app.logger.warning(f"403 error: {error}")
        return render_template(
            "error.html",
            error_title="Error",
            error_message="Access Denied",
            error_description="You don't have permission to access this page.",
            show_back=True,
            show_home=True,
        ), 403
