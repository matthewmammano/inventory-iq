"""Request rate limiting to blunt brute-force and abuse traffic.

Credential checks charge the auth limits only on rejection, so repeated correct
sign-ins never lock out a real user. Routes that send email on success charge
every attempt instead.

Storage is in-memory, which is correct only because the app runs a single
gunicorn worker (see docs/DEPLOYMENT.md). Add a shared backend (e.g. Redis)
before scaling to multiple workers or instances.
"""

from http import HTTPStatus

from flask import Flask, Response
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

DEFAULT_LIMITS = ("200 per minute", "2000 per hour")
AUTH_ATTEMPT_LIMITS = ("10 per minute", "50 per hour")
AUTH_RATE_LIMIT = "; ".join(AUTH_ATTEMPT_LIMITS)


def failed_auth_only(response: Response) -> bool:
    """Charge an auth limit only on rejection. Needs a route whose failure re-renders, not redirects."""
    return response.status_code != HTTPStatus.FOUND


limiter = Limiter(key_func=get_remote_address, default_limits=list(DEFAULT_LIMITS), storage_uri="memory://")


def register_rate_limiting(app: Flask) -> None:
    """Attach the shared limiter to the app."""
    limiter.init_app(app)
