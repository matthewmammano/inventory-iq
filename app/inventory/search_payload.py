"""Build browser search payloads from inventory ORM rows."""

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any, cast

from app.inventory.models import Items

if TYPE_CHECKING:
    from app.auth.models import AgencyItemTags


def build_item_search_payload(items: Iterable[Items]) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for item in items:
        tags = cast("list[AgencyItemTags]", item.tags)
        payload.append(
            {
                "id": item.id,
                "name": item.name,
                "upc": item.upc,
                "last_accessed": item.last_accessed.isoformat() if item.last_accessed else "",
                "tags": [tag.tag_name for tag in tags],
                "tag_data": [{"name": tag.tag_name, "color": tag.color, "text_color": tag.text_color} for tag in tags],
            }
        )
    return payload
