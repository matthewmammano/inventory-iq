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
from app.prediction.estimator import get_location_item_quantity
from app.prediction.validation import validate_location_restock

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
    item_ids: set[int],
) -> int:
    """Save one full-location count and queue related action alerts."""
    snapshots = _location_item_snapshots(session, agency_id, agency_location_id, item_ids)
    logs = save_location_count(session, agency_id, agency_location_id, quantities)
    record_action_log_alerts(
        session,
        logs,
        _updated_location_snapshots(session, agency_id, agency_location_id, snapshots),
    )
    return len(logs)


def save_bulk_location_restock(
    session: Session,
    agency_id: int,
    agency_location_id: int,
    quantities: QuantityGrid,
    item_ids: set[int],
) -> int:
    """Save one full-location vendor restock and queue related action alerts."""
    snapshots = _location_item_snapshots(session, agency_id, agency_location_id, item_ids)
    logs = save_location_restock(session, agency_id, agency_location_id, quantities)
    record_action_log_alerts(
        session,
        logs,
        _updated_location_snapshots(session, agency_id, agency_location_id, snapshots),
    )
    return len(logs)


def item_names_requiring_count(
    session: Session,
    agency_id: int,
    agency_location_id: int,
    items: list[Items],
) -> list[str]:
    """Return item names blocked from vendor restock until counted."""
    return [
        item.name
        for item in items
        if not validate_location_restock(agency_id, item.id, agency_location_id, session)[0]
    ]


def empty_quantity_grid(items: list[Items], storages: list[AgencyStorages]) -> QuantityGrid:
    """Build a zero-filled quantity grid for restock receipt forms."""
    return {(item.id, storage.id): 0 for item in items for storage in storages}


def item_ids(items: list[Items]) -> set[int]:
    """Return item IDs for snapshot operations."""
    return {item.id for item in items}


def _location_item_snapshots(
    session: Session,
    agency_id: int,
    agency_location_id: int,
    item_ids_to_snapshot: set[int],
) -> dict[int, int]:
    return {
        item_id: get_location_item_quantity(session, agency_id, item_id, agency_location_id)
        for item_id in item_ids_to_snapshot
    }


def _updated_location_snapshots(
    session: Session,
    agency_id: int,
    agency_location_id: int,
    previous_totals: dict[int, int],
) -> dict[tuple[int, int, int], tuple[int, int]]:
    return {
        (agency_id, item_id, agency_location_id): (
            before_total,
            get_location_item_quantity(session, agency_id, item_id, agency_location_id),
        )
        for item_id, before_total in previous_totals.items()
    }
