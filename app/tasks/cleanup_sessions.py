"""
Clean up expired Flask sessions.
Cron: 0 2 * * * python -m app.tasks.cleanup_sessions
"""

import time
from pathlib import Path
from app import create_app

def cleanup_expired_sessions():
    """Remove old session files"""
    app = create_app()
    with app.app_context():
        lifetime = app.config.get('PERMANENT_SESSION_LIFETIME')
        max_age = lifetime.total_seconds() if lifetime else 30 * 24 * 3600
        cutoff = time.time() - max_age

        cleaned = 0
        session_dirs = [
            Path('/tmp/flask_session'),
            Path(app.instance_path) / 'flask_session'
        ]

        for session_dir in session_dirs:
            if session_dir.exists():
                for session_file in session_dir.glob("session_*"):
                    if session_file.stat().st_mtime < cutoff:
                        session_file.unlink()
                        cleaned += 1

        print(f"Cleaned {cleaned} expired sessions")

if __name__ == "__main__":
    cleanup_expired_sessions()