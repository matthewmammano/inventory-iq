"""Build browser search payloads from inventory rows."""

from collections.abc import Iterable
from datetime import datetime
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.queries import get_tags_by_ids
from app.inventory.models import Items, ItemSecondaryUpc
from app.shared.cache import ttl_cache

if TYPE_CHECKING:
    from app.auth.models import AgencyItemTags


def build_item_search_payload(items: Iterable[Items]) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for item in items:
        tags = cast("list[AgencyItemTags]", item.tags)
        payload.append(_item_payload_entry(item.id, item.name, [item.upc, *(code.upc for code in item.secondary_upcs)], item.last_accessed, tags))
    return payload


@ttl_cache(skip_first_args=1)
def load_item_search_payload(
    session: Session,
    agency_id: int,
    *,
    include_inactive: bool = False,
    order_by_last_accessed: bool = False,
) -> list[dict[str, Any]]:
    """Load only the item fields needed by the scanner search payload."""
    stmt = select(
        Items.id,
        Items.name,
        Items.upc,
        Items.last_accessed,
        Items.tag_ids,
    ).where(Items.agency_id == agency_id)
    if not include_inactive:
        stmt = stmt.where(Items.active.is_(True))
    order_column = Items.last_accessed.desc().nulls_last() if order_by_last_accessed else Items.name
    rows = session.execute(stmt.order_by(order_column)).all()
    if not rows:
        return []

    tag_ids = sorted({tag_id for row in rows for tag_id in (row.tag_ids or [])})
    tags = get_tags_by_ids(agency_id, tag_ids, session=session) if tag_ids else []
    tags_by_id = {tag.id: tag for tag in tags}
    upcs_by_item_id = _upcs_by_item_id(session, agency_id, [row.id for row in rows])

    payload: list[dict[str, Any]] = []
    for row in rows:
        item_tags = [tags_by_id[tag_id] for tag_id in (row.tag_ids or []) if tag_id in tags_by_id]
        payload.append(_item_payload_entry(row.id, row.name, [row.upc, *upcs_by_item_id.get(row.id, [])], row.last_accessed, item_tags))
    return payload


def _upcs_by_item_id(session: Session, agency_id: int, item_ids: list[int]) -> dict[int, list[str]]:
    rows = session.execute(
        select(ItemSecondaryUpc.item_id, ItemSecondaryUpc.upc)
        .where(ItemSecondaryUpc.agency_id == agency_id, ItemSecondaryUpc.item_id.in_(item_ids))
        .order_by(ItemSecondaryUpc.item_id, ItemSecondaryUpc.upc)
    ).all()
    upcs_by_item: dict[int, list[str]] = {}
    for item_id, upc in rows:
        upcs_by_item.setdefault(item_id, []).append(upc)
    return upcs_by_item


def _item_payload_entry(
    item_id: int,
    name: str,
    upcs: list[str],
    last_accessed: datetime | None,
    tags: list[Any],
) -> dict[str, Any]:
    return {
        "id": item_id,
        "name": name,
        "upc": upcs[0] if upcs else "",
        "upcs": upcs,
        "last_accessed": last_accessed.isoformat() if last_accessed else "",
        "tags": [tag.tag_name for tag in tags],
        "tag_data": [{"name": tag.tag_name, "color": tag.color, "text_color": tag.text_color} for tag in tags],
    }
