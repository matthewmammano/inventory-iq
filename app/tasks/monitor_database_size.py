"""
Monthly database size monitoring and usage report.
Cron: 0 9 1 * * python -m app.tasks.monitor_database_size
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from flask import current_app
from flask_mailman import EmailMessage

from app import create_app, mail
from app.auth.models import Users
from app.inventory.models import ActionLogs, Items


def monitor_database_size() -> None:
    """Send monthly database size and usage report."""
    app = create_app()

    with app.app_context():
        db_size_mb = _get_database_size(app)
        stats = _get_database_stats()
        admin_email = _get_admin_email()

        if not admin_email:
            print("No admin email found")
            return

        _send_database_report(admin_email, db_size_mb, stats)
        print(f"Database report sent: {db_size_mb}MB, {stats['users']} users, {stats['items']} items")


def _get_database_size(app) -> float:
    """Get database size in MB."""
    db_path = Path(app.instance_path) / "inventory_iq.db"
    if db_path.exists():
        return round(db_path.stat().st_size / 1024 / 1024, 2)
    return 0.0


def _get_database_stats() -> dict:
    """Get database statistics."""
    thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)

    return {
        'users': Users.query.filter_by(active=True).count(),
        'items': Items.query.filter_by(active=True).count(),
        'recent_actions': ActionLogs.query.filter(ActionLogs.time_scanned >= thirty_days_ago).count()
    }


def _get_admin_email() -> Optional[str]:
    """Get admin email from config or first active user."""
    admin_email = current_app.config.get("MAIL_DEFAULT_SENDER")
    if admin_email:
        return admin_email

    first_user = Users.query.filter_by(active=True).first()
    return first_user.email if first_user else None


def _send_database_report(admin_email: str, db_size_mb: float, stats: dict) -> None:
    """Send database report email."""
    subject = f"Monthly Database Report - {datetime.now().strftime('%B %Y')}"
    body = f"""Monthly Database Report
======================

Database Size: {db_size_mb} MB
Active Users: {stats['users']}
Active Items: {stats['items']}
Actions (30 days): {stats['recent_actions']}

Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""

    msg = EmailMessage(
        subject=subject,
        body=body.strip(),
        from_email=current_app.config["MAIL_DEFAULT_SENDER"],
        to=[admin_email]
    )
    mail.send(msg)


if __name__ == "__main__":
    monitor_database_size()