"""Location repository for user item locations management.

Provides queries for UserItemLocations model:
- List locations by user
- Filter by access permissions (from/to)
- Location lookups for scan operations

All functions accept an optional `session` parameter for transaction control.
"""

from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import UserItemLocations
from app.db import managed_session


def list_locations(
    user_id: int,
    *,
    user_access_from: bool | None = None,
    user_access_to: bool | None = None,
    session: Session | None = None,
) -> list[UserItemLocations]:
    """List locations for a user, optionally filtered by access permissions.

    - `user_access_from=True`: only locations user can take from
    - `user_access_to=True`: only locations user can restock to
    - If both None: all user locations
    """
    with managed_session(session) as s:
        stmt = select(UserItemLocations).where(UserItemLocations.user_id == user_id)

        if user_access_from is True:
            stmt = stmt.where(UserItemLocations.user_access_from.is_(True))
        elif user_access_from is False:
            stmt = stmt.where(UserItemLocations.user_access_from.is_(False))

        if user_access_to is True:
            stmt = stmt.where(UserItemLocations.user_access_to.is_(True))
        elif user_access_to is False:
            stmt = stmt.where(UserItemLocations.user_access_to.is_(False))

        stmt = stmt.order_by(UserItemLocations.name)
        result: Iterable[UserItemLocations] = s.execute(stmt).scalars().all()
        return list(result)


def get_location(
    location_id: int, user_id: int, session: Session | None = None
) -> UserItemLocations | None:
    """Get a location by ID, validating it belongs to the user."""
    with managed_session(session) as s:
        stmt = select(UserItemLocations).where(
            UserItemLocations.id == location_id,
            UserItemLocations.user_id == user_id,
        )
        return s.execute(stmt).scalars().first()
