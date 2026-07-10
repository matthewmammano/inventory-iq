"""Current item/location state derived from storage balances and stock policy."""

from dataclasses import dataclass
from datetime import datetime

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.models import Agency, Location, Storage
from app.shared.clock import utc_now_naive

from .location_state_policy import effective_lead_time_days, evaluate_stock_state
from .models import ActionLog, InventoryItemLocationState, InventoryStorageBalance, Item


@dataclass(frozen=True, slots=True)
class ItemLocationKey:
    agency_id: int
    item_id: int
    agency_location_id: int


@dataclass(frozen=True)
class LocationStateRollup:
    """Rollup values needed to refresh one item/location state row."""

    total_quantity: int
    last_counted_at: datetime | None
    last_activity_at: datetime | None
    last_takeout_at: datetime | None


@dataclass(frozen=True)
class LocationStateSettings:
    """Scalar item/agency settings needed for state math."""

    min_quantity: int
    lead_time_days: int
    restock_delivery_days: int | None
    prior_daily_usage: float


@dataclass(frozen=True)
class LocationStateRebuildInput:
    """One active item/location pair with scalar settings."""

    agency_id: int
    item_id: int
    agency_location_id: int
    settings: LocationStateSettings


def sync_location_states_for_actions(session: Session, actions: list[ActionLog]) -> None:
    """Refresh item/location state rows affected by committed inventory actions."""
    keys = affected_item_location_keys_for_actions(session, actions)
    for key in sorted(keys, key=lambda value: (value.agency_id, value.item_id, value.agency_location_id)):
        recompute_item_location_state(session, key.agency_id, key.item_id, key.agency_location_id)
    if keys:
        session.flush()
        logger.debug(
            "Inventory item/location states refreshed for inventory actions",
            extra={"state_row_count": len(keys)},
        )


def rebuild_item_location_states(session: Session, agency_id: int | None = None) -> int:
    """Recompute all item/location state rows for active agencies/items."""
    rebuild_rows = _load_location_state_rebuild_rows(session, agency_id)
    existing_states = _state_rows_by_key(session, agency_id)
    location_rollups = _location_rollups_by_key(session, agency_id)
    desired_keys = {ItemLocationKey(row.agency_id, row.item_id, row.agency_location_id) for row in rebuild_rows}
    now = utc_now_naive()
    for rebuild_row in rebuild_rows:
        key = ItemLocationKey(rebuild_row.agency_id, rebuild_row.item_id, rebuild_row.agency_location_id)
        state = existing_states.get(key) or InventoryItemLocationState(
            agency_id=rebuild_row.agency_id,
            item_id=rebuild_row.item_id,
            agency_location_id=rebuild_row.agency_location_id,
        )
        _apply_state_values(state, rebuild_row.settings, location_rollups.get(key, _empty_location_rollup()), now)
        session.add(state)
    _delete_obsolete_state_rows(session, existing_states, desired_keys)
    session.flush()
    logger.info(
        "Inventory item/location states rebuilt",
        extra={"agency_id": agency_id, "state_row_count": len(rebuild_rows)},
    )
    return len(rebuild_rows)


def recompute_item_location_state(
    session: Session,
    agency_id: int,
    item_id: int,
    agency_location_id: int,
) -> InventoryItemLocationState | None:
    """Refresh one state row from current balances, item settings, and trend fields."""
    settings = _location_state_settings(session, agency_id, item_id, agency_location_id)
    existing = _existing_location_state(session, agency_id, item_id, agency_location_id)
    if settings is None:
        if existing is not None:
            session.delete(existing)
        return None

    state = existing or InventoryItemLocationState(
        agency_id=agency_id,
        item_id=item_id,
        agency_location_id=agency_location_id,
    )
    rollup = _load_location_rollup(session, agency_id, item_id, agency_location_id)
    now = utc_now_naive()
    _apply_state_values(state, settings, rollup, now)
    session.add(state)
    return state


def update_state_trend(
    session: Session,
    agency_id: int,
    item_id: int,
    agency_location_id: int,
    *,
    trend_per_day: float | None,
    confidence_percent: float | None,
    segment_count: int,
    data_signature: str | None,
    trained_at: datetime | None,
) -> InventoryItemLocationState | None:
    """Write trend fields to the current item/location state and refresh forecast math."""
    state = recompute_item_location_state(session, agency_id, item_id, agency_location_id)
    if state is None:
        return None
    state.trend_per_day = trend_per_day
    state.confidence_percent = confidence_percent
    state.segment_count = segment_count
    state.data_signature = data_signature
    state.trained_at = trained_at
    prior_daily_usage = session.scalar(
        select(Item.prior_daily_usage).where(
            Item.agency_id == agency_id,
            Item.id == item_id,
        )
    )
    if prior_daily_usage is None:
        return state
    _apply_stock_policy(
        state,
        settings=LocationStateSettings(
            min_quantity=state.min_quantity_snapshot,
            lead_time_days=state.lead_time_days_snapshot,
            restock_delivery_days=state.restock_delivery_days_snapshot,
            prior_daily_usage=float(prior_daily_usage),
        ),
    )
    now = utc_now_naive()
    state.state_version_at = _latest_datetime(state.last_activity_at, state.trained_at, now) or now
    state.updated_at = now
    return state


def _load_location_rollup(
    session: Session,
    agency_id: int,
    item_id: int,
    agency_location_id: int,
) -> LocationStateRollup:
    key = ItemLocationKey(agency_id, item_id, agency_location_id)
    rollups = _location_rollups_by_key(session, agency_id, item_id=item_id, agency_location_id=agency_location_id)
    return rollups.get(key, _empty_location_rollup())


def _empty_location_rollup() -> LocationStateRollup:
    return LocationStateRollup(
        total_quantity=0,
        last_counted_at=None,
        last_activity_at=None,
        last_takeout_at=None,
    )


def _apply_state_values(
    state: InventoryItemLocationState,
    settings: LocationStateSettings,
    rollup: LocationStateRollup,
    now: datetime,
) -> None:
    before = _state_value_signature(state)
    state.total_quantity = rollup.total_quantity
    state.last_counted_at = rollup.last_counted_at
    state.last_activity_at = rollup.last_activity_at
    state.last_takeout_at = rollup.last_takeout_at
    state.min_quantity_snapshot = settings.min_quantity
    state.lead_time_days_snapshot = settings.lead_time_days
    state.restock_delivery_days_snapshot = settings.restock_delivery_days
    _apply_stock_policy(state, settings=settings)
    state.state_version_at = _latest_datetime(state.state_version_at, rollup.last_activity_at, state.trained_at) or now
    if state.id is None or before != _state_value_signature(state):
        state.updated_at = now


def _state_value_signature(state: InventoryItemLocationState) -> tuple[object, ...]:
    return (
        state.total_quantity,
        state.last_counted_at,
        state.last_activity_at,
        state.last_takeout_at,
        state.min_quantity_snapshot,
        state.lead_time_days_snapshot,
        state.restock_delivery_days_snapshot,
        state.days_until_low,
        state.days_until_stockout,
        state.state_version_at,
    )


def _apply_stock_policy(
    state: InventoryItemLocationState,
    *,
    settings: LocationStateSettings,
) -> None:
    evaluation = evaluate_stock_state(
        total_quantity=state.total_quantity,
        min_quantity=settings.min_quantity,
        lead_time_days=settings.lead_time_days,
        prior_daily_usage=settings.prior_daily_usage,
        trend_per_day=state.trend_per_day,
    )
    state.days_until_low = evaluation.days_until_low
    state.days_until_stockout = evaluation.days_until_stockout


def _location_state_settings(
    session: Session,
    agency_id: int,
    item_id: int,
    agency_location_id: int,
) -> LocationStateSettings | None:
    key = ItemLocationKey(agency_id, item_id, agency_location_id)
    settings_by_key = _location_state_settings_by_key(session, agency_id, item_id=item_id, agency_location_id=agency_location_id)
    return settings_by_key.get(key)


def _load_location_state_rebuild_rows(session: Session, agency_id: int | None) -> list[LocationStateRebuildInput]:
    return [
        LocationStateRebuildInput(key.agency_id, key.item_id, key.agency_location_id, settings)
        for key, settings in _location_state_settings_by_key(session, agency_id).items()
    ]


def _location_state_settings_by_key(
    session: Session,
    agency_id: int | None,
    *,
    item_id: int | None = None,
    agency_location_id: int | None = None,
) -> dict[ItemLocationKey, LocationStateSettings]:
    stmt = (
        select(
            Item.agency_id,
            Item.id,
            Location.id,
            Item.min_quantity,
            Agency.lead_time_days,
            Item.restock_delivery_days,
            Item.prior_daily_usage,
        )
        .join(Agency, Agency.id == Item.agency_id)
        .join(Location, Location.agency_id == Item.agency_id)
        .where(Agency.active.is_(True), Item.active.is_(True))
        .order_by(Item.agency_id, Item.id, Location.id)
    )
    if agency_id is not None:
        stmt = stmt.where(Item.agency_id == agency_id)
    if item_id is not None:
        stmt = stmt.where(Item.id == item_id)
    if agency_location_id is not None:
        stmt = stmt.where(Location.id == agency_location_id)
    return {
        ItemLocationKey(row[0], row[1], row[2]): LocationStateSettings(
            min_quantity=int(row[3] or 0),
            lead_time_days=effective_lead_time_days(row[4], row[5]),
            restock_delivery_days=row[5],
            prior_daily_usage=float(row[6] or 0),
        )
        for row in session.execute(stmt).all()
    }


def _state_rows_by_key(
    session: Session,
    agency_id: int | None,
) -> dict[ItemLocationKey, InventoryItemLocationState]:
    stmt = select(InventoryItemLocationState)
    if agency_id is not None:
        stmt = stmt.where(InventoryItemLocationState.agency_id == agency_id)
    rows = session.execute(stmt).scalars()
    return {ItemLocationKey(row.agency_id, row.item_id, row.agency_location_id): row for row in rows}


def _location_rollups_by_key(
    session: Session,
    agency_id: int | None,
    *,
    item_id: int | None = None,
    agency_location_id: int | None = None,
) -> dict[ItemLocationKey, LocationStateRollup]:
    stmt = (
        select(
            InventoryStorageBalance.agency_id,
            InventoryStorageBalance.item_id,
            Storage.location_id,
            func.coalesce(func.sum(InventoryStorageBalance.quantity), 0),
            func.max(InventoryStorageBalance.last_counted_at),
            func.max(InventoryStorageBalance.updated_at),
            func.max(InventoryStorageBalance.last_takeout_at),
        )
        .join(Storage, Storage.id == InventoryStorageBalance.storage_id)
        .group_by(InventoryStorageBalance.agency_id, InventoryStorageBalance.item_id, Storage.location_id)
    )
    if agency_id is not None:
        stmt = stmt.where(InventoryStorageBalance.agency_id == agency_id)
    if item_id is not None:
        stmt = stmt.where(InventoryStorageBalance.item_id == item_id)
    if agency_location_id is not None:
        stmt = stmt.where(Storage.location_id == agency_location_id)
    return {
        ItemLocationKey(row[0], row[1], row[2]): LocationStateRollup(
            total_quantity=int(row[3] or 0),
            last_counted_at=row[4],
            last_activity_at=row[5],
            last_takeout_at=row[6],
        )
        for row in session.execute(stmt).all()
    }


def affected_item_location_keys_for_actions(
    session: Session,
    actions: list[ActionLog],
) -> set[ItemLocationKey]:
    """Return agency/item/location keys affected by inventory action storage IDs."""
    storage_ids = sorted(
        {
            storage_id
            for action in actions
            for storage_id in (action.from_storage_id, action.to_storage_id)
            if action.item_id is not None and storage_id is not None
        }
    )
    if not storage_ids:
        return set()
    storages = session.execute(select(Storage).where(Storage.id.in_(storage_ids))).scalars()
    location_by_storage_id = {storage.id: storage.location_id for storage in storages}
    keys: set[ItemLocationKey] = set()
    for action in actions:
        if action.item_id is None:
            continue
        for storage_id in (action.from_storage_id, action.to_storage_id):
            if storage_id is not None and storage_id in location_by_storage_id:
                keys.add(ItemLocationKey(action.agency_id, action.item_id, location_by_storage_id[storage_id]))
    return keys


def _existing_location_state(
    session: Session,
    agency_id: int,
    item_id: int,
    agency_location_id: int,
) -> InventoryItemLocationState | None:
    return session.scalar(
        select(InventoryItemLocationState).where(
            InventoryItemLocationState.agency_id == agency_id,
            InventoryItemLocationState.item_id == item_id,
            InventoryItemLocationState.agency_location_id == agency_location_id,
        )
    )


def _delete_obsolete_state_rows(
    session: Session,
    existing_rows: dict[ItemLocationKey, InventoryItemLocationState],
    desired_keys: set[ItemLocationKey],
) -> None:
    for key, row in existing_rows.items():
        if key not in desired_keys:
            session.delete(row)


def _latest_datetime(*values: datetime | None) -> datetime | None:
    clean_values = [value for value in values if value is not None]
    return max(clean_values) if clean_values else None
