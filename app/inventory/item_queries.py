"""Inventory repository for item management.

Provides CRUD operations and queries for Items model:
- Lookups by ID or user+UPC combination
- Item creation and updates
- User-specific item listings with filtering and ordering
- Item deactivation

All functions accept an optional `session` parameter for transaction control.
"""

from typing import Iterable

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import managed_session
from app.inventory.models import Items


def get_item(item_id: int, session: Session | None = None) -> Items | None:
    with managed_session(session) as s:
        stmt = select(Items).where(Items.id == item_id)
        return s.execute(stmt).scalars().first()


def get_item_by_upc(
    user_id: int, upc: str, session: Session | None = None
) -> Items | None:
    """Get item by user_id + upc (items are unique per user-UPC combo)."""
    with managed_session(session) as s:
        stmt = select(Items).where(Items.user_id == user_id, Items.upc == upc)
        return s.execute(stmt).scalars().first()


def list_items_for_user(
    user_id: int,
    include_inactive: bool,
    *,
    order_by_last_accessed: bool = False,
    session: Session | None = None,
) -> list[Items]:
    with managed_session(session) as s:
        stmt = select(Items).where(Items.user_id == user_id)
        if not include_inactive:
            stmt = stmt.where(Items.active)
        if order_by_last_accessed:
            stmt = stmt.order_by(Items.last_accessed.desc().nulls_last())
        else:
            stmt = stmt.order_by(Items.name)
        result: Iterable[Items] = s.execute(stmt).scalars().all()
        return list(result)


def create_item(
    name: str,
    upc: str | None,
    user_id: int,
    *,
    increments: str | None = None,
    image: str | None = None,
    session: Session | None = None,
) -> Items:
    with managed_session(session) as s:
        item = Items(
            name=name,
            upc=upc,
            user_id=user_id,
            increments=increments,
            image=image,
        )
        s.add(item)
        s.flush()
        logger.info(f"Created item {item.name} (id={item.id}) for user={user_id}")
        return item


def update_item(
    item_id: int,
    *,
    name: str | None = None,
    upc: str | None = None,
    increments: str | None = None,
    image: str | None = None,
    active: bool | None = None,
    session: Session | None = None,
) -> Items | None:
    with managed_session(session) as s:
        stmt = select(Items).where(Items.id == item_id)
        item = s.execute(stmt).scalars().first()
        if not item:
            return None
        if name is not None:
            item.name = name
        if upc is not None:
            item.upc = upc
        if increments is not None:
            item.increments = increments
        if image is not None:
            item.image = image
        if active is not None:
            item.active = active
        s.flush()
        logger.info(f"Updated item id={item_id}")
        return item


def deactivate_item(item_id: int, session: Session | None = None) -> bool:
    with managed_session(session) as s:
        stmt = select(Items).where(Items.id == item_id)
        item = s.execute(stmt).scalars().first()
        if not item:
            return False
        item.active = False
        s.flush()
        logger.info(f"Deactivated item id={item_id}")
        return True
