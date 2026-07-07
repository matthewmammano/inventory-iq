"""Bulk count/restock service for one agency location."""

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.alerts.alert_service import record_action_log_alerts
from app.auth.models import Agency, Location, Storage
from app.inventory.balance_service import get_required_count_storage_ids
from app.inventory.expiration_service import ExpirationAllocation, sync_expiration_lines_for_action
from app.inventory.item_queries import list_items
from app.inventory.location_operations import (
    build_location_count_rows,
    save_location_count,
    save_location_restock,
)
from app.inventory.location_state_service import sync_location_states_for_actions
from app.inventory.models import Item
from app.prediction.bulk_service import BulkService
from app.shared.clock import utc_now_naive

type StorageQuantityGrid = dict[tuple[int, int], int]


@dataclass(frozen=True)
class LocationQuantityGrid:
    """Template-ready item/storage quantities for one physical location."""

    location: Location
    items: list[Item]
    storages: list[Storage]
    quantities: StorageQuantityGrid


@dataclass(frozen=True)
class LocationItemSelection:
    """Template-ready location plus active item list."""

    location: Location
    items: list[Item]


@dataclass(frozen=True)
class LocationItemSummary:
    """Template-ready location plus active item count."""

    location: Location
    item_count: int


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


def load_location_item_selection(
    session: Session,
    agency_id: int,
    agency_location_id: int,
) -> LocationItemSelection | None:
    """Load location and active items without quantity grid work."""
    location = BulkService.get_location(session, agency_id, agency_location_id)
    if location is None:
        return None
    items = list_items(agency_id, order_by_last_accessed=True, session=session)
    return LocationItemSelection(location, items)


def load_location_item_summary(
    session: Session,
    agency_id: int,
    agency_location_id: int,
) -> LocationItemSummary | None:
    """Load location and active item count for the bulk-mode landing page."""
    location = BulkService.get_location(session, agency_id, agency_location_id)
    if location is None:
        return None
    item_count = int(session.scalar(select(func.count()).select_from(Item).where(Item.agency_id == agency_id, Item.active.is_(True))) or 0)
    return LocationItemSummary(location, item_count)


def save_bulk_location_count(
    session: Session,
    agency_id: int,
    agency_location_id: int,
    storage_quantities: StorageQuantityGrid,
    expiration_allocations_by_key: dict[str, list[ExpirationAllocation]] | None = None,
) -> int:
    """Save one full-location count and queue related action alerts."""
    logs = save_location_count(session, agency_id, agency_location_id, storage_quantities)
    _sync_bulk_expirations(session, logs, expiration_allocations_by_key or {})
    sync_location_states_for_actions(session, logs)
    record_action_log_alerts(session, logs)
    return len(logs)


def save_bulk_location_restock(
    session: Session,
    agency_id: int,
    agency_location_id: int,
    storage_quantities: StorageQuantityGrid,
    expiration_allocations_by_key: dict[str, list[ExpirationAllocation]] | None = None,
) -> int:
    """Save one full-location vendor restock and queue related action alerts."""
    logs = save_location_restock(session, agency_id, agency_location_id, storage_quantities)
    _sync_bulk_expirations(session, logs, expiration_allocations_by_key or {})
    sync_location_states_for_actions(session, logs)
    record_action_log_alerts(session, logs)
    return len(logs)


def required_count_storage_ids(
    session: Session,
    agency_id: int,
    agency_location_id: int,
    items: list[Item],
) -> dict[int, set[int]]:
    """Return stale storage IDs per item before restock is allowed."""
    if not items:
        return {}
    agency = session.get(Agency, agency_id)
    stale_days = int(agency.count_last_days if agency and agency.count_last_days else 1)
    cutoff = utc_now_naive() - timedelta(days=stale_days)
    return get_required_count_storage_ids(session, agency_id, agency_location_id, [item.id for item in items], cutoff)


def _sync_bulk_expirations(
    session: Session,
    logs,
    expiration_allocations_by_key: dict[str, list[ExpirationAllocation]],
) -> None:
    if not expiration_allocations_by_key:
        return
    for action in logs:
        if action.to_storage_id is None:
            continue
        key = f"{action.operation_type.value.lower()}_{action.item_id}_{action.to_storage_id}"
        sync_expiration_lines_for_action(session, action, expiration_allocations_by_key.get(key, []))
