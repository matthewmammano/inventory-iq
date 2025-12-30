"""Alert repository for user alerts management.

Provides queries for UserAlerts model:
- Get user alerts by user_id
- Centralized alert preference lookups

All functions accept an optional `session` parameter for transaction control.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import UserAlerts
from app.db import managed_session


def get_user_alerts(user_id: int, session: Session | None = None) -> UserAlerts | None:
    """Get UserAlerts record for a user."""
    with managed_session(session) as s:
        stmt = select(UserAlerts).where(UserAlerts.user_id == user_id)
        return s.execute(stmt).scalars().first()
