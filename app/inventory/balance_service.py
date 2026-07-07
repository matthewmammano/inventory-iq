"""Live inventory balance helpers derived from action history."""

from dataclasses import dataclass
from datetime import datetime

from loguru import logger
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, selectinload

from app.auth.models import Storage
from app.shared.clock import utc_now

from .models import ActionLog, InventoryStorageBalance, Item


@dataclass(frozen=True, order=True, slots=True)
class StorageBalanceKey:
    agency_id: int
    item_id: int
    storage_id: int


@dataclass
class BalanceState:
    """Computed current state for one agency/item/storage key."""

    quantity: int = 0
    last_counted_at: datetime | None = None
    last_takeout_at: datetime | None = None


@dataclass(frozen=True)
class BalanceReconciliationResult:
    """Summary of one reconciliation pass."""

    mismatch_count: int = 0
    repaired_row_count: int = 0


def sync_balances_for_actions(session: Session, actions: list[ActionLog]) -> None:
    """Apply committed action logs to the live balance table in the same transaction."""
    if not actions:
        return

    keys = _action_balance_keys(actions)
    existing_rows = _load_balance_rows(session, keys)
    for action in actions:
        _apply_action_to_rows(session, existing_rows, action)
    session.flush()


def rebuild_inventory_balances(session: Session, agency_id: int | None = None) -> int:
    """Recompute current balances from full history and replace live rows."""
    state_by_key = _computed_balance_state(session, agency_id)
    _delete_existing_balances(session, agency_id)
    if not state_by_key:
        return 0

    rows = [
        InventoryStorageBalance(
            agency_id=key.agency_id,
            item_id=key.item_id,
            storage_id=key.storage_id,
            quantity=state.quantity,
            last_counted_at=state.last_counted_at,
            last_takeout_at=state.last_takeout_at,
            updated_at=utc_now(),
        )
        for key, state in state_by_key.items()
    ]
    session.add_all(rows)
    session.flush()
    logger.info(
        "Inventory balances rebuilt from history",
        extra={"agency_id": agency_id, "balance_row_count": len(rows)},
    )
    return len(rows)


def reconcile_inventory_balances(
    session: Session,
    agency_id: int | None = None,
    *,
    repair: bool = False,
) -> BalanceReconciliationResult:
    """Compare history-derived truth to persisted live balances and optionally repair them."""
    expected = _computed_balance_state(session, agency_id)
    stored = _stored_balance_state(session, agency_id)
    mismatches = 0

    for key in sorted(set(expected) | set(stored)):
        expected_state = expected.get(key, BalanceState())
        stored_state = stored.get(key, BalanceState())
        if _states_match(expected_state, stored_state):
            continue
        mismatches += 1
        logger.error(
            "Inventory balance discrepancy detected",
            extra={
                "agency_id": key.agency_id,
                "item_id": key.item_id,
                "storage_id": key.storage_id,
                "expected_quantity": expected_state.quantity,
                "stored_quantity": stored_state.quantity,
                "expected_last_counted_at": _iso(expected_state.last_counted_at),
                "stored_last_counted_at": _iso(stored_state.last_counted_at),
                "expected_last_takeout_at": _iso(expected_state.last_takeout_at),
                "stored_last_takeout_at": _iso(stored_state.last_takeout_at),
            },
        )

    repaired_row_count = 0
    if mismatches and repair:
        repaired_row_count = rebuild_inventory_balances(session, agency_id)
        logger.warning(
            "Inventory balance discrepancies repaired from history",
            extra={
                "agency_id": agency_id,
                "mismatch_count": mismatches,
                "repair_scope": "full_agency_rebuild",
                "repaired_row_count": repaired_row_count,
                "repair_completed": True,
            },
        )

    logger.info(
        "Inventory balance reconciliation finished",
        extra={
            "agency_id": agency_id,
            "mismatch_count": mismatches,
            "repaired": repair and mismatches > 0,
            "repair_scope": "full_agency_rebuild" if repair and mismatches > 0 else None,
            "repaired_row_count": repaired_row_count,
        },
    )
    return BalanceReconciliationResult(
        mismatch_count=mismatches,
        repaired_row_count=repaired_row_count,
    )


def get_item_quantities(
    session: Session,
    agency_id: int,
    item_id: int,
) -> dict[int, int]:
    """Return current quantity by storage for one item from the live balance table."""
    rows = session.execute(
        select(InventoryStorageBalance.storage_id, InventoryStorageBalance.quantity).where(
            InventoryStorageBalance.agency_id == agency_id,
            InventoryStorageBalance.item_id == item_id,
        )
    ).all()
    return {storage_id: int(quantity) for storage_id, quantity in rows}


def build_location_quantity_rows(
    session: Session,
    agency_id: int,
    agency_location_id: int,
    *,
    include_secondary_upcs: bool = False,
) -> tuple[list[Item], list[Storage], dict[tuple[int, int], int]]:
    """Return items, storages, and current quantities for one physical location."""
    item_stmt = select(Item).where(Item.agency_id == agency_id, Item.active.is_(True)).order_by(Item.name)
    if include_secondary_upcs:
        item_stmt = item_stmt.options(selectinload(Item.secondary_upcs))
    items = list(session.execute(item_stmt).scalars().all())
    storages = list(
        session.execute(
            select(Storage)
            .where(
                Storage.agency_id == agency_id,
                Storage.location_id == agency_location_id,
            )
            .order_by(Storage.name)
        )
        .scalars()
        .all()
    )
    storage_ids = [storage.id for storage in storages]
    counts = _location_counts(session, agency_id, storage_ids)
    return items, storages, counts


def get_location_item_total(
    session: Session,
    agency_id: int,
    item_id: int,
    agency_location_id: int,
) -> int:
    """Return the current total for one item across all storages in a location."""
    total = session.scalar(
        select(func.coalesce(func.sum(InventoryStorageBalance.quantity), 0))
        .join(Storage, Storage.id == InventoryStorageBalance.storage_id)
        .where(
            InventoryStorageBalance.agency_id == agency_id,
            InventoryStorageBalance.item_id == item_id,
            Storage.location_id == agency_location_id,
        )
    )
    return int(total or 0)


def get_location_item_totals(
    session: Session,
    agency_id: int,
    agency_location_id: int,
    item_ids: list[int],
) -> dict[int, int]:
    """Return current totals for many items in one location."""
    if not item_ids:
        return {}
    rows = session.execute(
        select(
            InventoryStorageBalance.item_id,
            func.coalesce(func.sum(InventoryStorageBalance.quantity), 0),
        )
        .join(Storage, Storage.id == InventoryStorageBalance.storage_id)
        .where(
            InventoryStorageBalance.agency_id == agency_id,
            InventoryStorageBalance.item_id.in_(item_ids),
            Storage.location_id == agency_location_id,
        )
        .group_by(InventoryStorageBalance.item_id)
    ).all()
    return {item_id: int(total) for item_id, total in rows}


def get_location_last_counted_dates(
    session: Session,
    agency_id: int,
    agency_location_id: int,
    item_ids: list[int],
) -> dict[int, datetime]:
    """Return latest count timestamps per item inside one location."""
    if not item_ids:
        return {}
    rows = session.execute(
        select(
            InventoryStorageBalance.item_id,
            func.max(InventoryStorageBalance.last_counted_at),
        )
        .join(Storage, Storage.id == InventoryStorageBalance.storage_id)
        .where(
            InventoryStorageBalance.agency_id == agency_id,
            InventoryStorageBalance.item_id.in_(item_ids),
            Storage.location_id == agency_location_id,
            InventoryStorageBalance.last_counted_at.is_not(None),
        )
        .group_by(InventoryStorageBalance.item_id)
    ).all()
    return {item_id: counted_at for item_id, counted_at in rows if counted_at is not None}


def get_location_last_counted_at(
    session: Session,
    agency_id: int,
    item_id: int,
    agency_location_id: int,
) -> datetime | None:
    """Return the latest count timestamp for one item inside one location."""
    return _location_balance_timestamp(
        session,
        agency_id,
        item_id,
        agency_location_id,
        InventoryStorageBalance.last_counted_at,
    )


def get_location_last_takeout_at(
    session: Session,
    agency_id: int,
    item_id: int,
    agency_location_id: int,
) -> datetime | None:
    """Return the latest takeout timestamp for one item inside one location."""
    return _location_balance_timestamp(
        session,
        agency_id,
        item_id,
        agency_location_id,
        InventoryStorageBalance.last_takeout_at,
    )


def get_required_count_storage_ids(
    session: Session,
    agency_id: int,
    agency_location_id: int,
    item_ids: list[int],
    cutoff: datetime,
) -> dict[int, set[int]]:
    """Return stale storage IDs per item using the live balance table."""
    storages = list(
        session.execute(
            select(Storage.id)
            .where(
                Storage.agency_id == agency_id,
                Storage.location_id == agency_location_id,
            )
            .order_by(Storage.name)
        ).all()
    )
    storage_ids = [storage_id for (storage_id,) in storages]
    if not item_ids or not storage_ids:
        return {}

    rows = session.execute(
        select(
            InventoryStorageBalance.item_id,
            InventoryStorageBalance.storage_id,
            InventoryStorageBalance.last_counted_at,
        ).where(
            InventoryStorageBalance.agency_id == agency_id,
            InventoryStorageBalance.item_id.in_(item_ids),
            InventoryStorageBalance.storage_id.in_(storage_ids),
        )
    ).all()
    counted_at_by_key = {(item_id, storage_id): counted_at for item_id, storage_id, counted_at in rows}
    required: dict[int, set[int]] = {}
    for item_id in item_ids:
        stale_storage_ids = {
            storage_id for storage_id in storage_ids if (counted_at := counted_at_by_key.get((item_id, storage_id))) is None or counted_at < cutoff
        }
        if stale_storage_ids:
            required[item_id] = stale_storage_ids
    return required


def has_balance_rows(session: Session, agency_id: int, item_id: int) -> bool:
    """Return whether the live balance table already has rows for one item."""
    row = session.execute(
        select(InventoryStorageBalance.id)
        .where(
            InventoryStorageBalance.agency_id == agency_id,
            InventoryStorageBalance.item_id == item_id,
        )
        .limit(1)
    ).first()
    return row is not None


def _action_balance_keys(actions: list[ActionLog]) -> set[StorageBalanceKey]:
    keys: set[StorageBalanceKey] = set()
    for action in actions:
        if action.item_id is None:
            continue
        if action.from_storage_id is not None:
            keys.add(StorageBalanceKey(action.agency_id, action.item_id, action.from_storage_id))
        if action.to_storage_id is not None:
            keys.add(StorageBalanceKey(action.agency_id, action.item_id, action.to_storage_id))
    return keys


def _load_balance_rows(
    session: Session,
    keys: set[StorageBalanceKey],
) -> dict[StorageBalanceKey, InventoryStorageBalance]:
    if not keys:
        return {}
    agency_ids = sorted({key.agency_id for key in keys})
    item_ids = sorted({key.item_id for key in keys})
    storage_ids = sorted({key.storage_id for key in keys})
    rows = session.execute(
        select(InventoryStorageBalance).where(
            InventoryStorageBalance.agency_id.in_(agency_ids),
            InventoryStorageBalance.item_id.in_(item_ids),
            InventoryStorageBalance.storage_id.in_(storage_ids),
        )
    ).scalars()
    return {StorageBalanceKey(row.agency_id, row.item_id, row.storage_id): row for row in rows}


def _apply_action_to_rows(
    session: Session,
    row_by_key: dict[StorageBalanceKey, InventoryStorageBalance],
    action: ActionLog,
) -> None:
    if action.item_id is None:
        return
    if action.is_count and action.to_storage_id is not None:
        row = _ensure_row(session, row_by_key, action.agency_id, action.item_id, action.to_storage_id)
        row.quantity = action.quantity
        row.last_counted_at = action.time_scanned
        row.updated_at = utc_now()
        return

    if action.to_storage_id is not None:
        row = _ensure_row(session, row_by_key, action.agency_id, action.item_id, action.to_storage_id)
        row.quantity += action.quantity
        row.updated_at = utc_now()
    if action.from_storage_id is not None:
        row = _ensure_row(session, row_by_key, action.agency_id, action.item_id, action.from_storage_id)
        row.quantity -= action.quantity
        if action.is_takeout:
            row.last_takeout_at = action.time_scanned
        row.updated_at = utc_now()


def _ensure_row(
    session: Session,
    row_by_key: dict[StorageBalanceKey, InventoryStorageBalance],
    agency_id: int,
    item_id: int,
    storage_id: int,
) -> InventoryStorageBalance:
    key = StorageBalanceKey(agency_id, item_id, storage_id)
    row = row_by_key.get(key)
    if row is not None:
        return row
    row = InventoryStorageBalance(
        agency_id=agency_id,
        item_id=item_id,
        storage_id=storage_id,
        quantity=0,
        updated_at=utc_now(),
    )
    session.add(row)
    row_by_key[key] = row
    return row


def _computed_balance_state(session: Session, agency_id: int | None) -> dict[StorageBalanceKey, BalanceState]:
    stmt = select(
        ActionLog.agency_id,
        ActionLog.item_id,
        ActionLog.operation_type,
        ActionLog.from_storage_id,
        ActionLog.to_storage_id,
        ActionLog.quantity,
        ActionLog.time_scanned,
    ).where(ActionLog.item_id.is_not(None))
    if agency_id is not None:
        stmt = stmt.where(ActionLog.agency_id == agency_id)
    stmt = stmt.order_by(ActionLog.agency_id, ActionLog.item_id, ActionLog.time_scanned, ActionLog.id)

    state_by_key: dict[StorageBalanceKey, BalanceState] = {}
    for row in session.execute(stmt):
        row_agency_id = int(row.agency_id)
        row_item_id = int(row.item_id)
        if row.operation_type.is_count and row.to_storage_id is not None:
            state = state_by_key.setdefault(StorageBalanceKey(row_agency_id, row_item_id, int(row.to_storage_id)), BalanceState())
            state.quantity = int(row.quantity)
            state.last_counted_at = row.time_scanned
            continue
        if row.to_storage_id is not None:
            state = state_by_key.setdefault(StorageBalanceKey(row_agency_id, row_item_id, int(row.to_storage_id)), BalanceState())
            state.quantity += int(row.quantity)
        if row.from_storage_id is not None:
            state = state_by_key.setdefault(StorageBalanceKey(row_agency_id, row_item_id, int(row.from_storage_id)), BalanceState())
            state.quantity -= int(row.quantity)
            if row.operation_type.is_takeout:
                state.last_takeout_at = row.time_scanned
    return state_by_key


def _stored_balance_state(session: Session, agency_id: int | None) -> dict[StorageBalanceKey, BalanceState]:
    stmt = select(
        InventoryStorageBalance.agency_id,
        InventoryStorageBalance.item_id,
        InventoryStorageBalance.storage_id,
        InventoryStorageBalance.quantity,
        InventoryStorageBalance.last_counted_at,
        InventoryStorageBalance.last_takeout_at,
    )
    if agency_id is not None:
        stmt = stmt.where(InventoryStorageBalance.agency_id == agency_id)
    rows = session.execute(stmt).all()
    return {
        StorageBalanceKey(row.agency_id, row.item_id, row.storage_id): BalanceState(
            quantity=int(row.quantity),
            last_counted_at=row.last_counted_at,
            last_takeout_at=row.last_takeout_at,
        )
        for row in rows
    }


def _delete_existing_balances(session: Session, agency_id: int | None) -> None:
    stmt = delete(InventoryStorageBalance)
    if agency_id is not None:
        stmt = stmt.where(InventoryStorageBalance.agency_id == agency_id)
    session.execute(stmt)


def _states_match(expected: BalanceState, stored: BalanceState) -> bool:
    return (
        expected.quantity == stored.quantity
        and expected.last_counted_at == stored.last_counted_at
        and expected.last_takeout_at == stored.last_takeout_at
    )


def _location_counts(
    session: Session,
    agency_id: int,
    storage_ids: list[int],
) -> dict[tuple[int, int], int]:
    if not storage_ids:
        return {}
    rows = session.execute(
        select(
            InventoryStorageBalance.item_id,
            InventoryStorageBalance.storage_id,
            InventoryStorageBalance.quantity,
        ).where(
            InventoryStorageBalance.agency_id == agency_id,
            InventoryStorageBalance.storage_id.in_(storage_ids),
        )
    ).all()
    return {(item_id, storage_id): int(quantity) for item_id, storage_id, quantity in rows}


def _location_balance_timestamp(
    session: Session,
    agency_id: int,
    item_id: int,
    agency_location_id: int,
    column,
) -> datetime | None:
    return session.scalar(
        select(func.max(column))
        .join(Storage, Storage.id == InventoryStorageBalance.storage_id)
        .where(
            InventoryStorageBalance.agency_id == agency_id,
            InventoryStorageBalance.item_id == item_id,
            Storage.location_id == agency_location_id,
            column.is_not(None),
        )
    )


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None
