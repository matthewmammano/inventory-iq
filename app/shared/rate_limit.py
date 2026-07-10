"""Request rate limiting to blunt brute-force and abuse traffic.

Storage is in-memory, which is correct only because the app runs a single
gunicorn worker (see docs/DEPLOYMENT.md). Add a shared backend (e.g. Redis)
before scaling to multiple workers or instances.
"""

from flask import Flask
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

DEFAULT_LIMITS = ("200 per minute", "2000 per hour")
AUTH_ATTEMPT_LIMITS = ("10 per minute", "50 per hour")

limiter = Limiter(key_func=get_remote_address, default_limits=list(DEFAULT_LIMITS))


def register_rate_limiting(app: Flask) -> None:
    """Attach the shared limiter to the app."""
    limiter.init_app(app)
