"""Action log repository for inventory operation history.

Provides reusable query patterns for ActionLogs model.
Only includes functions used in multiple places (2+ usages).
"""

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.inventory.constants import OperationType
from app.inventory.models import ActionLogs


def get_recent_admin_count(
    user_id: int,
    item_id: int,
    location_id: int,
    hours_back: int,
    session: Session | None = None,
) -> ActionLogs | None:
    """Get most recent admin COUNT at location within hours_back."""
    from app.db import managed_session

    with managed_session(session) as s:
        cutoff_time = datetime.now() - timedelta(hours=hours_back)
        stmt = (
            select(ActionLogs)
            .where(
                ActionLogs.user_id == user_id,
                ActionLogs.item_id == item_id,
                ActionLogs.to_location_id == location_id,
                ActionLogs.operation_type == OperationType.count,
                ActionLogs.admin_action.is_(True),
                ActionLogs.time_scanned >= cutoff_time,
            )
            .order_by(ActionLogs.time_scanned.desc())
        )
        return s.execute(stmt).scalars().first()
