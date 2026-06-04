"""Bulk count/restock service for one agency location."""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.alerts.alert_service import record_action_log_alerts
from app.auth.models import AgencyLocations, AgencyStorages
from app.inventory.location_operations import (
    build_location_count_rows,
    save_location_count,
    save_location_restock,
)
from app.inventory.models import Items
from app.prediction.bulk_service import BulkService
from app.prediction.validation import get_stale_count_storage_ids

type QuantityGrid = dict[tuple[int, int], int]


@dataclass(frozen=True)
class LocationQuantityGrid:
    """Template-ready item/storage quantities for one physical location."""

    location: AgencyLocations
    items: list[Items]
    storages: list[AgencyStorages]
    quantities: QuantityGrid


def load_location_quantity_grid(
    session: Session,
    agency_id: int,
    agency_location_id: int,
) -> LocationQuantityGrid | None:
    """Load location, items, storages, and current quantities."""
    location = BulkService.get_location(session, agency_id, agency_location_id)
    if location is None:
        return None
    items, storages, quantities = build_location_count_rows(session, agency_id, agency_location_id)
    return LocationQuantityGrid(location, items, storages, quantities)


def save_bulk_location_count(
    session: Session,
    agency_id: int,
    agency_location_id: int,
    quantities: QuantityGrid,
) -> int:
    """Save one full-location count and queue related action alerts."""
    logs = save_location_count(session, agency_id, agency_location_id, quantities)
    record_action_log_alerts(session, logs)
    return len(logs)


def save_bulk_location_restock(
    session: Session,
    agency_id: int,
    agency_location_id: int,
    quantities: QuantityGrid,
) -> int:
    """Save one full-location vendor restock and queue related action alerts."""
    logs = save_location_restock(session, agency_id, agency_location_id, quantities)
    record_action_log_alerts(session, logs)
    return len(logs)


def required_count_storage_ids(
    session: Session,
    agency_id: int,
    agency_location_id: int,
    items: list[Items],
) -> dict[int, set[int]]:
    """Return stale storage IDs per item before restock is allowed."""
    return {item.id: set(get_stale_count_storage_ids(agency_id, item.id, agency_location_id, session)) for item in items}
