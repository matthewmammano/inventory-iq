"""JSON API surface consumed by the React frontend."""

from app.api import agency_access  # noqa: F401  importing installs the agency gate on the blueprint
from app.api.blueprint import api_bp

__all__ = ["api_bp"]
