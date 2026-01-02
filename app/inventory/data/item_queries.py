"""Inventory repository for item management.

Provides CRUD operations and queries for Items model:
- Lookups by ID or user+UPC combination
- Item creation and updates
- User-specific item listings with filtering and ordering
- Item deactivation

All functions accept an optional `session` parameter for transaction control.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Iterable

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session, managed_session
from app.inventory.data.models import Items


@dataclass
class BatchUpdateResult:
    """Result of batch item update operation."""

    new_count: int
    deleted_count: int
    errors: list[str]


def get_item(item_id: int, session: Session | None = None) -> Items | None:
    """Get single item by ID."""
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
    """List all items for a user with optional filtering."""
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


def batch_update_items(user_id: int, items_json: str | None) -> BatchUpdateResult:
    """Batch create, update, delete items from JSON form data.

    Returns operation summary with error tracking. Validates tag_ids and item names.
    """
    from app.auth.tag_queries import get_tags_by_ids

    if not items_json:
        logger.warning(f"No item data for user {user_id}")
        return BatchUpdateResult(new_count=0, deleted_count=0, errors=["No data"])

    try:
        items_list = json.loads(items_json)
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error for user {user_id}: {e}")
        return BatchUpdateResult(new_count=0, deleted_count=0, errors=["Invalid JSON"])

    with get_session() as session:
        existing_ids = {
            item.id for item in list_items_for_user(user_id, True, session=session)
        }

    processed_ids: set[int] = set()
    new_items = []
    error_items = []

    # Process each item (create or update)
    for item_data in items_list:
        name = item_data.get("name", "").strip()
        if not name:
            error_items.append("Unnamed Item")
            continue

        item_id = item_data.get("id")
        active = item_data.get("active", True)
        tag_ids = item_data.get("tag_ids", [])
        if isinstance(tag_ids, str):
            tag_ids = [
                int(x.strip()) for x in tag_ids.split(",") if x.strip().isdigit()
            ]
        increments = item_data.get("increments")
        image = item_data.get("image", "").strip()

        # Validate tag_ids
        if tag_ids:
            try:
                with get_session() as s:
                    valid_tags = list(get_tags_by_ids(user_id, tag_ids, session=s))
                if len(valid_tags) != len(tag_ids):
                    error_items.append(name)
                    continue
            except (ValueError, TypeError):
                error_items.append(name)
                continue

        # Create or update
        if item_id != "new" and item_id is not None:
            try:
                item_id = int(item_id)
                processed_ids.add(item_id)

                with get_session() as session:
                    item = get_item(item_id, session)
                    if not item or item.user_id != user_id:
                        error_items.append(name)
                        continue

                    item.name = name
                    item.active = active
                    item.tag_ids = tag_ids
                    item.increments = increments if increments else None
                    item.image = image if image else None
                    session.add(item)
                    session.commit()
            except (ValueError, TypeError):
                error_items.append(name)
                continue
        else:
            # Create new
            try:
                item = Items(
                    active=active,
                    tag_ids=tag_ids,
                    increments=increments if increments else None,
                    name=name,
                    image=image if image else None,
                    user_id=user_id,
                )
                with get_session() as session:
                    session.add(item)
                    session.flush()
                new_items.append(item)
            except Exception as e:
                logger.error(f"Error creating item {name} for user {user_id}: {e}")
                error_items.append(name)
                continue

    # Delete removed items
    deleted_count = 0
    with get_session() as session:
        for item_id in existing_ids - processed_ids:
            item_to_delete = get_item(item_id, session)
            if item_to_delete and item_to_delete.user_id == user_id:
                session.delete(item_to_delete)
                deleted_count += 1

    logger.info(
        f"User {user_id} batch update: {len(new_items)} new, {deleted_count} deleted, {len(error_items)} errors"
    )

    return BatchUpdateResult(
        new_count=len(new_items), deleted_count=deleted_count, errors=error_items
    )
