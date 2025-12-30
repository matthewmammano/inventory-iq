"""User repository for authentication and user management.

Provides CRUD operations and common queries for Users model:
- Lookups by ID, email, or display name
- User creation with password hashing
- User updates and deactivation
- Filtered user listings

All functions accept an optional `session` parameter for transaction control.
"""

from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import Users
from app.db import managed_session


def get_user(user_id: int, session: Session | None = None) -> Users | None:
    with managed_session(session) as s:
        stmt = select(Users).where(Users.id == user_id)
        return s.execute(stmt).scalars().first()


def get_user_by_email(email: str, session: Session | None = None) -> Users | None:
    with managed_session(session) as s:
        stmt = select(Users).where(Users.email == email)
        return s.execute(stmt).scalars().first()


def get_user_by_display_name(
    display_name: str, session: Session | None = None
) -> Users | None:
    with managed_session(session) as s:
        stmt = select(Users).where(Users.display_name == display_name)
        return s.execute(stmt).scalars().first()


def list_users(active: bool, session: Session | None = None) -> list[Users]:
    """List users filtered by `active`.

    - `active=True`: only active users
    - `active=False`: only inactive users
    """
    with managed_session(session) as s:
        stmt = select(Users)
        stmt = stmt.where(Users.active.is_(active))
        stmt = stmt.order_by(Users.display_name)
        result: Iterable[Users] = s.execute(stmt).scalars().all()
        return list(result)


def get_user_permissions(
    display_name: str, session: Session | None = None
) -> tuple[bool, bool, bool] | None:
    """Get user scan permissions (count_allow, restock_allow, take_allow).

    Returns:
        Tuple of (count, restock, takeout) permissions or None if user not found
    """
    with managed_session(session) as s:
        stmt = select(
            Users.user_count_allow, Users.user_restock_allow, Users.user_take_allow
        ).where(Users.display_name == display_name)
        row = s.execute(stmt).first()
        return row if row else None
