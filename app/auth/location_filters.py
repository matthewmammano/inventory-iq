"""Location filter helpers for agency notification recipients."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session


def normalize_location_filter_ids(value: Any) -> list[int] | None:
    """Return sorted unique location IDs; None means all locations."""
    if value in (None, ""):
        return None
    if not isinstance(value, list):
        raise ValueError("location_filter_ids must be a list of location IDs")

    location_ids: set[int] = set()
    for location_id in value:
        if isinstance(location_id, bool):
            raise ValueError("location_filter_ids must contain integers")
        location_ids.add(int(location_id))
    return sorted(location_ids) or None


def validate_location_filter_ids(
    session: Session,
    agency_id: int,
    location_ids: list[int] | None,
) -> list[int] | None:
    """Ensure selected locations belong to the recipient's agency."""
    location_ids = normalize_location_filter_ids(location_ids)
    if location_ids is None:
        return None

    from app.auth.models import AgencyLocations

    valid_ids = set(
        session.execute(
            select(AgencyLocations.id).where(
                AgencyLocations.agency_id == agency_id,
                AgencyLocations.id.in_(location_ids),
            )
        ).scalars()
    )
    invalid_ids = sorted(set(location_ids) - valid_ids)
    if invalid_ids:
        raise ValueError(f"Location IDs do not belong to agency: {invalid_ids}")
    return location_ids


def alert_matches_location_filter(
    location_filter_ids: list[int] | None,
    details: dict[str, Any],
) -> bool:
    """Return True when an alert touches at least one selected location."""
    location_filter_ids = normalize_location_filter_ids(location_filter_ids)
    if location_filter_ids is None:
        return True

    alert_location_ids = {
        int(location_id)
        for key in ("agency_location_id", "from_agency_location_id", "to_agency_location_id")
        if (location_id := details.get(key)) is not None
    }
    return not alert_location_ids or bool(alert_location_ids & set(location_filter_ids))
