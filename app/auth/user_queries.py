"""User repository for authentication and user management.

Provides CRUD operations and common queries for Users model:
- Lookups by ID, email, or display name
- User creation with password hashing
- User updates and deactivation
- Filtered user listings

All functions accept an optional `session` parameter for transaction control.
"""

from typing import Iterable

from loguru import logger
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


def create_user(
    display_name: str,
    email: str,
    pin: str,
    timezone: str,
    *,
    password: str | None = None,
    image: str | None = None,
    notes: str | None = None,
    user_count_allow: bool = False,
    user_restock_allow: bool = False,
    user_take_allow: bool = True,
    session: Session | None = None,
) -> Users:
    with managed_session(session) as s:
        user = Users(
            display_name=display_name,
            email=email,
            pin=pin,
            timezone=timezone,
            image=image,
            notes=notes,
            user_count_allow=user_count_allow,
            user_restock_allow=user_restock_allow,
            user_take_allow=user_take_allow,
        )
        if password:
            user.set_password(password)
        s.add(user)
        s.flush()
        logger.info(f"Created user {user.display_name} (id={user.id})")
        return user


def update_user(
    user_id: int,
    *,
    display_name: str | None = None,
    email: str | None = None,
    pin: str | None = None,
    timezone: str | None = None,
    image: str | None = None,
    notes: str | None = None,
    user_count_allow: bool | None = None,
    user_restock_allow: bool | None = None,
    user_take_allow: bool | None = None,
    password: str | None = None,
    active: bool | None = None,
    session: Session | None = None,
) -> Users | None:
    with managed_session(session) as s:
        stmt = select(Users).where(Users.id == user_id)
        user = s.execute(stmt).scalars().first()
        if not user:
            return None
        if display_name is not None:
            user.display_name = display_name
        if email is not None:
            user.email = email
        if pin is not None:
            user.pin = pin
        if timezone is not None:
            user.timezone = timezone
        if image is not None:
            user.image = image
        if notes is not None:
            user.notes = notes
        if user_count_allow is not None:
            user.user_count_allow = user_count_allow
        if user_restock_allow is not None:
            user.user_restock_allow = user_restock_allow
        if user_take_allow is not None:
            user.user_take_allow = user_take_allow
        if active is not None:
            user.active = active
        if password:
            user.set_password(password)
        s.flush()
        logger.info(f"Updated user id={user_id}")
        return user


def deactivate_user(user_id: int, session: Session | None = None) -> bool:
    with managed_session(session) as s:
        stmt = select(Users).where(Users.id == user_id)
        user = s.execute(stmt).scalars().first()
        if not user:
            return False
        user.active = False
        s.flush()
        logger.info(f"Deactivated user id={user_id}")
        return True
