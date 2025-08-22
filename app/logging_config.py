"""
Simple logging setup optimized for Railway deployment.
"""

import json
import logging
import os
from datetime import datetime


class JSONFormatter(logging.Formatter):
    """Railway-optimized JSON formatter."""

    def format(self, record):
        log_data = {
            "time": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "module": record.module,
        }

        # Add user context if available (best effort)
        try:
            from flask import has_request_context
            from flask_login import current_user

            if has_request_context() and current_user and current_user.is_authenticated:
                log_data["user"] = getattr(current_user, 'email', 'unknown')
        except Exception:
            pass

        return json.dumps(log_data)


def setup_logging():
    """Setup Railway-optimized logging (stdout only)."""
    env = os.environ.get("FLASK_ENV", "prod")
    is_dev = env in ["dev", "development"]
    
    # Single console handler - Railway captures everything
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(JSONFormatter())

    # Simple environment-based levels
    log_level = logging.DEBUG if is_dev else logging.INFO
    logging.basicConfig(level=log_level, handlers=[console_handler])
    
    # Quiet noisy loggers in production
    if not is_dev:
        logging.getLogger("werkzeug").setLevel(logging.WARNING)
        logging.getLogger("urllib3").setLevel(logging.WARNING)
