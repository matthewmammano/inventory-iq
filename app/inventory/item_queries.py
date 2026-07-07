"""Inventory item query helpers."""

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.auth.queries import get_tags_by_ids
from app.shared.database import managed_session

from .models import Item, ItemSecondaryUpc


def get_agency_item(
    agency_id: int,
    item_id: int,
    *,
    include_inactive: bool = False,
    session: Session | None = None,
) -> Item | None:
    with managed_session(session) as db:
        stmt = select(Item).where(Item.id == item_id, Item.agency_id == agency_id)
        if not include_inactive:
            stmt = stmt.where(Item.active.is_(True))
        return db.execute(stmt).scalars().first()


def get_item_by_upc(
    agency_id: int,
    upc: str,
    *,
    include_inactive: bool = False,
    session: Session | None = None,
) -> Item | None:
    with managed_session(session) as db:
        normalized = upc.strip()
        stmt = select(Item).where(Item.agency_id == agency_id, Item.upc == normalized)
        if not include_inactive:
            stmt = stmt.where(Item.active.is_(True))
        item = db.execute(stmt).scalars().first()
        if item is not None:
            return item
        stmt = select(Item).join(ItemSecondaryUpc).where(Item.agency_id == agency_id, ItemSecondaryUpc.upc == normalized)
        if not include_inactive:
            stmt = stmt.where(Item.active.is_(True), ItemSecondaryUpc.active.is_(True))
        return db.execute(stmt).scalars().first()


def list_items(
    agency_id: int,
    *,
    include_inactive: bool = False,
    order_by_last_accessed: bool = False,
    session: Session | None = None,
) -> list[Item]:
    with managed_session(session) as db:
        stmt = select(Item).options(selectinload(Item.secondary_upcs)).where(Item.agency_id == agency_id)
        if not include_inactive:
            stmt = stmt.where(Item.active.is_(True))
        order_column = Item.last_accessed.desc().nulls_last() if order_by_last_accessed else Item.name
        items = list(db.execute(stmt.order_by(order_column)).scalars().all())
        _attach_tags(agency_id, items, db)
        return items


def _attach_tags(agency_id: int, items: list[Item], session: Session) -> None:
    for item in items:
        item.secondary_upcs = [code for code in item.secondary_upcs if code.active]
    tag_ids = {tag_id for item in items for tag_id in (item.tag_ids or [])}
    if not tag_ids:
        for item in items:
            item.tags = []
        return

    tags = get_tags_by_ids(agency_id, sorted(tag_ids), session=session)
    tag_by_id = {tag.id: tag for tag in tags}
    for item in items:
        item.tags = [tag_by_id[tag_id] for tag_id in (item.tag_ids or []) if tag_id in tag_by_id]
