"""Inventory item query helpers."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.queries import get_tags_by_ids
from app.shared.database import managed_session

from .models import Items


def get_agency_item(
    agency_id: int,
    item_id: int,
    *,
    include_inactive: bool = False,
    session: Session | None = None,
) -> Items | None:
    with managed_session(session) as db:
        stmt = select(Items).where(Items.id == item_id, Items.agency_id == agency_id)
        if not include_inactive:
            stmt = stmt.where(Items.active.is_(True))
        return db.execute(stmt).scalars().first()


def get_item_by_upc(
    agency_id: int,
    upc: str,
    *,
    include_inactive: bool = False,
    session: Session | None = None,
) -> Items | None:
    with managed_session(session) as db:
        stmt = select(Items).where(Items.agency_id == agency_id, Items.upc == upc)
        if not include_inactive:
            stmt = stmt.where(Items.active.is_(True))
        return db.execute(stmt).scalars().first()


def list_items(
    agency_id: int,
    *,
    include_inactive: bool = False,
    order_by_last_accessed: bool = False,
    session: Session | None = None,
) -> list[Items]:
    with managed_session(session) as db:
        stmt = select(Items).where(Items.agency_id == agency_id)
        if not include_inactive:
            stmt = stmt.where(Items.active.is_(True))
        order_column = (
            Items.last_accessed.desc().nulls_last() if order_by_last_accessed else Items.name
        )
        items = list(db.execute(stmt.order_by(order_column)).scalars().all())
        _attach_tags(agency_id, items, db)
        return items


def _attach_tags(agency_id: int, items: list[Items], session: Session) -> None:
    tag_ids = {tag_id for item in items for tag_id in (item.tag_ids or [])}
    if not tag_ids:
        for item in items:
            item.tags = []
        return

    tags = get_tags_by_ids(agency_id, sorted(tag_ids), session=session)
    tag_by_id = {tag.id: tag for tag in tags}
    for item in items:
        item.tags = [tag_by_id[tag_id] for tag_id in (item.tag_ids or []) if tag_id in tag_by_id]
