"""Clean up expired Flask session files.
Cron: 0 2 * * * python tasks/cleanup_sessions.py
"""

import time
from pathlib import Path

from loguru import logger

from app import create_app


def cleanup_expired_sessions() -> None:
    app = create_app()
    with app.app_context():
        lifetime = app.config.get("PERMANENT_SESSION_LIFETIME")
        max_age = lifetime.total_seconds() if lifetime else 30 * 24 * 3600
        cutoff = time.time() - max_age

        cleaned = 0
        for session_dir in [Path("/tmp/flask_session"), Path(app.instance_path) / "flask_session"]:
            if session_dir.exists():
                for f in session_dir.glob("session_*"):
                    if f.stat().st_mtime < cutoff:
                        f.unlink()
                        cleaned += 1

        logger.info(f"Cleaned {cleaned} expired sessions")


if __name__ == "__main__":
    cleanup_expired_sessions()
