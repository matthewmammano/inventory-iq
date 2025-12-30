"""Tag repository for user item tags management.

Provides queries for UserItemTags model:
- List tags by user
- Get tags by IDs with user validation
- Tag lookups for filtering

All functions accept an optional `session` parameter for transaction control.
"""

from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import UserItemTags
from app.db import managed_session


def list_tags(user_id: int, session: Session | None = None) -> list[UserItemTags]:
    """List all tags for a user, ordered by tag name."""
    with managed_session(session) as s:
        stmt = (
            select(UserItemTags)
            .where(UserItemTags.user_id == user_id)
            .order_by(UserItemTags.tag_name)
        )
        result: Iterable[UserItemTags] = s.execute(stmt).scalars().all()
        return list(result)


def get_tags_by_ids(
    user_id: int, tag_ids: list[int], session: Session | None = None
) -> list[UserItemTags]:
    """Get tags by IDs, validating they belong to the user."""
    with managed_session(session) as s:
        stmt = select(UserItemTags).where(
            UserItemTags.id.in_(tag_ids),
            UserItemTags.user_id == user_id,
        )
        result: Iterable[UserItemTags] = s.execute(stmt).scalars().all()
        return list(result)
