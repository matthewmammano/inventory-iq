"""Security response headers applied to every response."""

from flask import Flask, Response

from app.shared.config import settings

_CSP_DIRECTIVES = (
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' https://fonts.googleapis.com",
    "font-src 'self' https://fonts.gstatic.com",
    "img-src 'self' data: https:",  # agencies can set an externally-hosted logo URL (see Agency.image / validate_image_url)
    "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
)
CONTENT_SECURITY_POLICY = "; ".join(_CSP_DIRECTIVES)
PERMISSIONS_POLICY = "geolocation=(), microphone=(), camera=()"
HSTS_MAX_AGE_SECONDS = 63_072_000  # two years, matches common HSTS preload guidance


def register_security_headers(app: Flask) -> None:
    """Attach hardened response headers to every request."""

    @app.after_request
    def _apply_security_headers(response: Response) -> Response:
        response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = PERMISSIONS_POLICY
        if settings.is_prod:
            response.headers["Strict-Transport-Security"] = f"max-age={HSTS_MAX_AGE_SECONDS}; includeSubDomains"
        return response
