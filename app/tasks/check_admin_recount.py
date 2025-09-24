"""
Check items needing admin recount.
Cron: 0 5 * * * python -m app.tasks.check_admin_recount
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import and_

from app import create_app, db
from app.auth.models import UserAlerts, Users
from app.inventory.models import ActionLogs, Items, OperationType


def check_admin_count_alerts() -> None:
    """Generate alerts for items needing admin count."""
    app = create_app()

    with app.app_context():
        alerts_added = 0
        user_alerts = UserAlerts.query.filter(UserAlerts.count_last_days > 0).all()

        for user_alert in user_alerts:
            user = db.session.get(Users, user_alert.user_id)
            if not user or not user.active:
                continue

            alerts_added += _process_user_items(user, user_alert)

        db.session.commit()
        print(f"Generated {alerts_added} admin count alerts")


def _process_user_items(user: Users, user_alert: UserAlerts) -> int:
    """Process items for a user and generate alerts."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=user_alert.count_last_days)
    items = Items.query.filter_by(user_id=user.id, active=True).all()
    alerts_added = 0

    for item in items:
        if not _has_recent_admin_count(user.id, item.id, cutoff):
            _add_alert(user_alert, item.name, user_alert.count_last_days)
            alerts_added += 1

    return alerts_added


def _has_recent_admin_count(user_id: int, item_id: int, cutoff: datetime) -> bool:
    """Check if item has recent admin count."""
    return (
        ActionLogs.query.filter(
            and_(
                ActionLogs.user_id == user_id,
                ActionLogs.item_id == item_id,
                ActionLogs.operation_type == OperationType.count,
                ActionLogs.admin_action.is_(True),
                ActionLogs.time_scanned >= cutoff,
            )
        ).first()
        is not None
    )


def _add_alert(user_alert: UserAlerts, item_name: str, days: int) -> None:
    """Add alert to user's pending alerts."""
    if not user_alert.pending_alerts:
        user_alert.pending_alerts = []

    user_alert.pending_alerts.append(
        {"type": "count_admin", "item": item_name, "urgent": False, "data": {"days": days}}
    )


if __name__ == "__main__":
    check_admin_count_alerts()
