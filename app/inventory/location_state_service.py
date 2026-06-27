"""Current item/location state derived from storage balances and trend fields."""

from dataclasses import dataclass
from datetime import datetime

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.alerts.constants import STOCK_ALERT_RANK, AlertSeverity, AlertType
from app.auth.models import Agencies, AgencyLocations, AgencyStorages
from app.prediction.constants import MAX_EFFECTIVE_DAILY_USAGE, MIN_EFFECTIVE_DAILY_USAGE
from app.shared.clock import utc_now_naive

from .models import ActionLogs, InventoryItemLocationState, InventoryStorageBalances, Items


@dataclass(frozen=True)
class LocationStateInput:
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


def sync_location_states_for_actions(session: Session, actions: list[ActionLogs]) -> None:
    """Refresh item/location state rows affected by committed inventory actions."""
    keys = _affected_item_location_keys(session, actions)
    for agency_id, item_id, agency_location_id in sorted(keys):
        recompute_item_location_state(session, agency_id, item_id, agency_location_id)
    if keys:
        session.flush()
        logger.debug(
            "Inventory item/location states refreshed for inventory actions",
            extra={"state_row_count": len(keys)},
        )


def rebuild_item_location_states(session: Session, agency_id: int | None = None) -> int:
    """Recompute all item/location state rows for active agencies/items."""
    rows = _location_state_rebuild_inputs(session, agency_id)
    states = _state_rows_by_key(session, agency_id)
    rollups = _location_rollups_by_key(session, agency_id)
    now = utc_now_naive()
    for row in rows:
        key = (row.agency_id, row.item_id, row.agency_location_id)
        state = states.get(key) or InventoryItemLocationState(
            agency_id=row.agency_id,
            item_id=row.item_id,
            agency_location_id=row.agency_location_id,
        )
        _apply_state_values(state, row.settings, rollups.get(key, _empty_rollup()), now)
        session.add(state)
    session.flush()
    logger.info(
        "Inventory item/location states rebuilt",
        extra={"agency_id": agency_id, "state_row_count": len(rows)},
    )
    return len(rows)


def recompute_item_location_state(
    session: Session,
    agency_id: int,
    item_id: int,
    agency_location_id: int,
) -> InventoryItemLocationState | None:
    """Refresh one state row from current balances, item settings, and trend fields."""
    settings = _location_state_settings(session, agency_id, item_id, agency_location_id)
    if settings is None:
        return None

    existing = _state_row(session, agency_id, item_id, agency_location_id)
    state = existing or InventoryItemLocationState(
        agency_id=agency_id,
        item_id=item_id,
        agency_location_id=agency_location_id,
    )
    rollup = _location_rollup(session, agency_id, item_id, agency_location_id)
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
        select(Items.prior_daily_usage).where(
            Items.agency_id == agency_id,
            Items.id == item_id,
        )
    )
    if prior_daily_usage is None:
        return state
    _apply_forecast_fields(state, float(prior_daily_usage))
    _apply_effective_alert_fields(state)
    now = utc_now_naive()
    state.state_version_at = _latest_datetime(state.last_activity_at, state.trained_at, now) or now
    state.updated_at = now
    return state


def _apply_forecast_fields(state: InventoryItemLocationState, prior_daily_usage: float) -> None:
    trend_per_day = state.trend_per_day if state.trend_per_day is not None else -float(prior_daily_usage or 0)
    daily_usage = _effective_daily_usage(trend_per_day)
    forecast_trend = -daily_usage
    state.days_until_low = _days_to_threshold(state.total_quantity, forecast_trend, state.min_quantity_snapshot)
    state.days_until_stockout = _days_to_threshold(state.total_quantity, forecast_trend, 0)


def _apply_effective_alert_fields(state: InventoryItemLocationState) -> None:
    state.stock_status = _stock_status(state.total_quantity, state.min_quantity_snapshot)
    state.forecast_status = _forecast_status(state)
    winner = _winning_stock_alert(state.stock_status, state.forecast_status)
    state.effective_alert_type = winner
    state.effective_alert_rank = STOCK_ALERT_RANK.get(winner, 0) if winner else 0
    state.effective_severity = _severity_for_state(state, winner)


def _stock_status(total_quantity: int, min_quantity: int) -> AlertType | None:
    if total_quantity <= 0:
        return AlertType.STOCKOUT
    if total_quantity < min_quantity:
        return AlertType.LOW_STOCK
    return None


def _forecast_status(state: InventoryItemLocationState) -> AlertType | None:
    if state.lead_time_days_snapshot <= 0:
        return None
    if _within_lead_time(state.days_until_stockout, state.lead_time_days_snapshot):
        return AlertType.STOCKOUT_FORECAST
    if _within_lead_time(state.days_until_low, state.lead_time_days_snapshot):
        return AlertType.LOW_STOCK_FORECAST
    return None


def _winning_stock_alert(*alert_types: AlertType | None) -> AlertType | None:
    winner: AlertType | None = None
    winner_rank = -1
    for alert_type in alert_types:
        if alert_type is None:
            continue
        rank = STOCK_ALERT_RANK[alert_type]
        if rank > winner_rank:
            winner = alert_type
            winner_rank = rank
    return winner


def _severity_for_state(state: InventoryItemLocationState, alert_type: AlertType | None) -> AlertSeverity | None:
    if alert_type == AlertType.STOCKOUT:
        return AlertSeverity.CRITICAL
    if alert_type == AlertType.LOW_STOCK:
        return AlertSeverity.HIGH if state.total_quantity <= max(state.min_quantity_snapshot // 2, 0) else AlertSeverity.WARNING
    if alert_type == AlertType.STOCKOUT_FORECAST:
        return _forecast_severity(state.days_until_stockout, state.lead_time_days_snapshot)
    if alert_type == AlertType.LOW_STOCK_FORECAST:
        return _forecast_severity(state.days_until_low, state.lead_time_days_snapshot)
    return None


def _forecast_severity(days_until_threshold: float | None, lead_time_days: int) -> AlertSeverity | None:
    if days_until_threshold is None or days_until_threshold > lead_time_days:
        return None
    if days_until_threshold <= 1:
        return AlertSeverity.CRITICAL
    if days_until_threshold <= 3:
        return AlertSeverity.HIGH
    if days_until_threshold <= 7:
        return AlertSeverity.WARNING
    return AlertSeverity.NOTICE


def _location_rollup(
    session: Session,
    agency_id: int,
    item_id: int,
    agency_location_id: int,
) -> LocationStateInput:
    row = session.execute(
        select(
            func.coalesce(func.sum(InventoryStorageBalances.quantity), 0),
            func.max(InventoryStorageBalances.last_counted_at),
            func.max(InventoryStorageBalances.last_activity_at),
            func.max(InventoryStorageBalances.last_takeout_at),
        )
        .join(AgencyStorages, AgencyStorages.id == InventoryStorageBalances.storage_id)
        .where(
            InventoryStorageBalances.agency_id == agency_id,
            InventoryStorageBalances.item_id == item_id,
            AgencyStorages.location_id == agency_location_id,
        )
    ).one()
    return LocationStateInput(
        total_quantity=int(row[0] or 0),
        last_counted_at=row[1],
        last_activity_at=row[2],
        last_takeout_at=row[3],
    )


def _empty_rollup() -> LocationStateInput:
    return LocationStateInput(
        total_quantity=0,
        last_counted_at=None,
        last_activity_at=None,
        last_takeout_at=None,
    )


def _apply_state_values(
    state: InventoryItemLocationState,
    settings: LocationStateSettings,
    rollup: LocationStateInput,
    now: datetime,
) -> None:
    state.total_quantity = rollup.total_quantity
    state.last_counted_at = rollup.last_counted_at
    state.last_activity_at = rollup.last_activity_at
    state.last_takeout_at = rollup.last_takeout_at
    state.min_quantity_snapshot = settings.min_quantity
    state.lead_time_days_snapshot = settings.lead_time_days
    state.restock_delivery_days_snapshot = settings.restock_delivery_days
    _apply_forecast_fields(state, settings.prior_daily_usage)
    _apply_effective_alert_fields(state)
    state.state_version_at = _latest_datetime(rollup.last_activity_at, state.trained_at, now) or now
    state.updated_at = now


def _location_state_settings(
    session: Session,
    agency_id: int,
    item_id: int,
    agency_location_id: int,
) -> LocationStateSettings | None:
    row = session.execute(
        select(
            Items.min_quantity,
            Agencies.lead_time_days,
            Items.restock_delivery_days,
            Items.prior_daily_usage,
        )
        .join(Agencies, Agencies.id == Items.agency_id)
        .join(AgencyLocations, AgencyLocations.agency_id == Agencies.id)
        .where(
            Agencies.id == agency_id,
            Items.id == item_id,
            Items.active.is_(True),
            AgencyLocations.id == agency_location_id,
        )
    ).one_or_none()
    if row is None:
        return None
    return LocationStateSettings(
        min_quantity=int(row[0] or 0),
        lead_time_days=_effective_lead_time_days(row[1], row[2]),
        restock_delivery_days=row[2],
        prior_daily_usage=float(row[3] or 0),
    )


def _location_state_rebuild_inputs(session: Session, agency_id: int | None) -> list[LocationStateRebuildInput]:
    stmt = (
        select(
            Items.agency_id,
            Items.id,
            AgencyLocations.id,
            Items.min_quantity,
            Agencies.lead_time_days,
            Items.restock_delivery_days,
            Items.prior_daily_usage,
        )
        .join(Agencies, Agencies.id == Items.agency_id)
        .join(AgencyLocations, AgencyLocations.agency_id == Items.agency_id)
        .where(Agencies.active.is_(True), Items.active.is_(True))
        .order_by(Items.agency_id, Items.id, AgencyLocations.id)
    )
    if agency_id is not None:
        stmt = stmt.where(Items.agency_id == agency_id)
    return [
        LocationStateRebuildInput(
            agency_id=row[0],
            item_id=row[1],
            agency_location_id=row[2],
            settings=LocationStateSettings(
                min_quantity=int(row[3] or 0),
                lead_time_days=_effective_lead_time_days(row[4], row[5]),
                restock_delivery_days=row[5],
                prior_daily_usage=float(row[6] or 0),
            ),
        )
        for row in session.execute(stmt).all()
    ]


def _state_rows_by_key(
    session: Session,
    agency_id: int | None,
) -> dict[tuple[int, int, int], InventoryItemLocationState]:
    stmt = select(InventoryItemLocationState)
    if agency_id is not None:
        stmt = stmt.where(InventoryItemLocationState.agency_id == agency_id)
    rows = session.execute(stmt).scalars()
    return {(row.agency_id, row.item_id, row.agency_location_id): row for row in rows}


def _location_rollups_by_key(
    session: Session,
    agency_id: int | None,
) -> dict[tuple[int, int, int], LocationStateInput]:
    stmt = (
        select(
            InventoryStorageBalances.agency_id,
            InventoryStorageBalances.item_id,
            AgencyStorages.location_id,
            func.coalesce(func.sum(InventoryStorageBalances.quantity), 0),
            func.max(InventoryStorageBalances.last_counted_at),
            func.max(InventoryStorageBalances.last_activity_at),
            func.max(InventoryStorageBalances.last_takeout_at),
        )
        .join(AgencyStorages, AgencyStorages.id == InventoryStorageBalances.storage_id)
        .group_by(InventoryStorageBalances.agency_id, InventoryStorageBalances.item_id, AgencyStorages.location_id)
    )
    if agency_id is not None:
        stmt = stmt.where(InventoryStorageBalances.agency_id == agency_id)
    return {
        (row[0], row[1], row[2]): LocationStateInput(
            total_quantity=int(row[3] or 0),
            last_counted_at=row[4],
            last_activity_at=row[5],
            last_takeout_at=row[6],
        )
        for row in session.execute(stmt).all()
    }


def _affected_item_location_keys(
    session: Session,
    actions: list[ActionLogs],
) -> set[tuple[int, int, int]]:
    storage_ids = sorted(
        {
            storage_id
            for action in actions
            for storage_id in (action.from_location_id, action.to_location_id)
            if action.item_id is not None and storage_id is not None
        }
    )
    if not storage_ids:
        return set()
    storages = session.execute(select(AgencyStorages).where(AgencyStorages.id.in_(storage_ids))).scalars()
    location_by_storage_id = {storage.id: storage.location_id for storage in storages}
    keys: set[tuple[int, int, int]] = set()
    for action in actions:
        if action.item_id is None:
            continue
        for storage_id in (action.from_location_id, action.to_location_id):
            if storage_id is not None and storage_id in location_by_storage_id:
                keys.add((action.agency_id, action.item_id, location_by_storage_id[storage_id]))
    return keys


def _state_row(
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


def _effective_daily_usage(trend_per_day: float) -> float:
    usage = max(0.0, -float(trend_per_day))
    return min(max(usage, MIN_EFFECTIVE_DAILY_USAGE), MAX_EFFECTIVE_DAILY_USAGE)


def _days_to_threshold(current_quantity: int, trend_per_day: float, threshold: float) -> float | None:
    if current_quantity <= threshold:
        return 0.0
    if trend_per_day >= 0:
        return None
    return round((float(current_quantity) - threshold) / abs(trend_per_day), 1)


def _within_lead_time(days_until_threshold: float | None, lead_time_days: int) -> bool:
    return days_until_threshold is not None and 0 <= days_until_threshold <= lead_time_days


def _effective_lead_time_days(agency_lead_time_days: int | None, item_restock_delivery_days: int | None) -> int:
    value = item_restock_delivery_days if item_restock_delivery_days is not None else agency_lead_time_days
    return int(value or 0)


def _latest_datetime(*values: datetime | None) -> datetime | None:
    clean_values = [value for value in values if value is not None]
    return max(clean_values) if clean_values else None
