"""
Check items needing admin recount.
Cron: 0 5 * * * python -m app.tasks.check_admin_recount
"""

from datetime import UTC, datetime, timedelta

from loguru import logger
from sqlalchemy import and_, select

from app import create_app
from app.auth.models import UserAlerts, Users
from app.db import get_session
from app.inventory.models import ActionLogs, Items, OperationType


def check_admin_count_alerts() -> None:
    """Generate alerts for items needing admin count."""
    app = create_app()

    with app.app_context():
        alerts_added = 0
        with get_session() as session:
            stmt = select(UserAlerts).where(UserAlerts.count_last_days > 0)
            user_alerts = session.execute(stmt).scalars().all()

            for user_alert in user_alerts:
                user = session.get(Users, user_alert.user_id)
                if not user or not user.active:
                    continue

                alerts_added += _process_user_items(session, user, user_alert)

            session.commit()
        logger.info(f"Generated {alerts_added} admin count alerts")


def _process_user_items(session, user: Users, user_alert: UserAlerts) -> int:
    """Process items for a user and generate alerts."""
    days = user_alert.count_last_days or 0
    cutoff = datetime.now(UTC) - timedelta(days=days)
    items = (
        session.execute(
            select(Items).where(Items.user_id == user.id, Items.active.is_(True))
        )
        .scalars()
        .all()
    )
    alerts_added = 0

    for item in items:
        if not _has_recent_admin_count(session, user.id, item.id, cutoff):
            _add_alert(user_alert, item.name, days)
            alerts_added += 1

    return alerts_added


def _has_recent_admin_count(
    session, user_id: int, item_id: int, cutoff: datetime
) -> bool:
    """Check if item has recent admin count."""
    stmt = select(ActionLogs).where(
        and_(
            ActionLogs.user_id == user_id,
            ActionLogs.item_id == item_id,
            ActionLogs.operation_type == OperationType.count,
            ActionLogs.admin_action.is_(True),
            ActionLogs.time_scanned >= cutoff,
        )
    )
    return session.execute(stmt).scalars().first() is not None


def _add_alert(user_alert: UserAlerts, item_name: str, days: int) -> None:
    """Add alert to user's pending alerts."""
    if not user_alert.pending_alerts:
        user_alert.pending_alerts = []

    user_alert.pending_alerts.append(
        {
            "type": "count_admin",
            "item": item_name,
            "urgent": False,
            "data": {"days": days},
        }
    )


if __name__ == "__main__":
    check_admin_count_alerts()
