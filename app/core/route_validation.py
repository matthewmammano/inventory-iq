"""
Shared route validation and authorization service.

Eliminates duplicate squad validation and auth checks across admin/guest routes.
"""

from datetime import UTC, datetime

from flask import flash, request, session, url_for
from flask_login import current_user
from loguru import logger

from app.core.data_access import DataAccessService


class RouteValidationService:
    """Centralized route validation and authorization."""

    @staticmethod
    def validate_squad_access(squad: str, require_active: bool = True) -> str | None:
        """
        Validate squad exists and is accessible.

        Args:
            squad: Squad name to validate
            require_active: If True, squad must be active

        Returns:
            None if valid, error redirect URL if invalid
        """
        if not squad:
            flash("Squad name is required.", "warning")
            return url_for("auth.login")

        # Get user by squad name using centralized service
        user = DataAccessService.get_user_by_squad(squad)
        if not user:
            flash("Invalid squad name. Please try again.", "error")
            return url_for("auth.login")

        if require_active and not user.active:
            flash("This squad is now inactive. Please contact support.", "warning")
            return url_for("auth.login")

        return None  # Valid

    @staticmethod
    def validate_user_authentication() -> str | None:
        """
        Validate user is authenticated.

        Returns:
            None if valid, error redirect URL if invalid
        """
        if not current_user.is_authenticated:
            flash("You must be logged in to access this page.", "warning")
            return url_for("auth.login")

        return None  # Valid

    @staticmethod
    def validate_admin_session(squad: str, timeout_seconds: int = 21600) -> str | None:
        """
        Validate admin session is active and not expired.

        Args:
            squad: Squad name for redirect
            timeout_seconds: Session timeout in seconds

        Returns:
            None if valid, error redirect URL if invalid
        """
        if not session.get("admin"):
            session.pop("admin", None)
            session.pop("admin_last_active", None)
            logger.warning(
                f"Admin session not found for user {current_user.email} in squad {squad}"
            )
            flash("Admin session not found. Please log in with PIN.", "warning")
            return url_for("guest.index", squad=squad)

        now = datetime.now(UTC).timestamp()
        admin_last_active = session.get("admin_last_active")

        if not admin_last_active or now - admin_last_active > timeout_seconds:
            session.pop("admin", None)
            session.pop("admin_last_active", None)
            logger.warning(
                f"Admin session expired for user {current_user.email} in squad {squad}"
            )
            flash(
                "Admin session expired. Please log in with your PIN again.", "warning"
            )
            return url_for("guest.index", squad=squad)

        # Update last active timestamp
        session["admin_last_active"] = now
        return None  # Valid

    @staticmethod
    def get_squad_from_request() -> str | None:
        """Get squad parameter from current request."""
        return request.view_args.get("squad") if request.view_args else None

    @staticmethod
    def is_static_request() -> bool:
        """Check if current request is for static assets."""
        return request.endpoint is not None and "static" in request.endpoint
