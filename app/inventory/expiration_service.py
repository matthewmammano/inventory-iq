"""Expiration-date inventory balance helpers."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.shared.clock import utc_now

from .constants import OperationType
from .models import ActionLog, ActionLogExpirationLine, InventoryExpirationBalance, InventoryStorageBalance, Item


@dataclass(frozen=True, order=True, slots=True)
class ExpirationBalanceKey:
    agency_id: int
    item_id: int
    storage_id: int
    expires_on: date


@dataclass(frozen=True, slots=True)
class ExpirationAllocation:
    expires_on: date | None
    quantity: int


def effective_expiration_notice_days(item: Item, agency_default_days: int) -> int:
    """Return item-specific expiration notice days, falling back to the agency default."""
    return int(item.expiration_notice_days_override or agency_default_days)


def known_expiration_options(
    session: Session,
    agency_id: int,
    item_id: int,
    storage_id: int,
) -> list[InventoryExpirationBalance]:
    """Return positive tracked expiration quantities for scan selection."""
    return list(
        session.execute(
            select(InventoryExpirationBalance)
            .where(
                InventoryExpirationBalance.agency_id == agency_id,
                InventoryExpirationBalance.item_id == item_id,
                InventoryExpirationBalance.storage_id == storage_id,
                InventoryExpirationBalance.quantity > 0,
            )
            .order_by(InventoryExpirationBalance.expires_on, InventoryExpirationBalance.id)
        )
        .scalars()
        .all()
    )


def sync_expiration_lines_for_action(
    session: Session,
    action: ActionLog,
    allocations: Sequence[ExpirationAllocation],
) -> None:
    """Attach expiration allocations to an action and update expiration balances."""
    if action.item_id is None:
        return
    _validate_allocations(action, allocations)
    lines = [ActionLogExpirationLine(action_log=action, expires_on=line.expires_on, quantity=line.quantity) for line in allocations]
    session.add_all(lines)
    _apply_allocations_to_balances(session, action, allocations)
    session.flush()


def expiration_count_needed(session: Session, agency_id: int, item_id: int, storage_id: int) -> bool:
    """Return whether tracked expiration quantity disagrees with total storage quantity."""
    total_quantity = session.scalar(
        select(InventoryStorageBalance.quantity).where(
            InventoryStorageBalance.agency_id == agency_id,
            InventoryStorageBalance.item_id == item_id,
            InventoryStorageBalance.storage_id == storage_id,
        )
    )
    expiration_quantity = session.scalar(
        select(func.coalesce(func.sum(InventoryExpirationBalance.quantity), 0)).where(
            InventoryExpirationBalance.agency_id == agency_id,
            InventoryExpirationBalance.item_id == item_id,
            InventoryExpirationBalance.storage_id == storage_id,
        )
    )
    return int(total_quantity or 0) != int(expiration_quantity or 0)


def save_expiration_count_correction(
    session: Session,
    agency_id: int,
    item_id: int,
    storage_id: int,
    allocations: Sequence[ExpirationAllocation],
) -> None:
    """Replace expiration quantities for a known storage count without writing inventory history."""
    storage_quantity = session.scalar(
        select(InventoryStorageBalance.quantity).where(
            InventoryStorageBalance.agency_id == agency_id,
            InventoryStorageBalance.item_id == item_id,
            InventoryStorageBalance.storage_id == storage_id,
        )
    )
    if storage_quantity is None:
        raise ValueError("Item count not found for this storage.")
    _validate_allocation_total(
        allocations,
        int(storage_quantity),
        "Expiration quantities must match the current item count.",
    )
    corrected_at = utc_now()
    _replace_storage_expiration_balances(
        session,
        agency_id,
        item_id,
        storage_id,
        [allocation for allocation in allocations if allocation.expires_on is not None],
        counted_at=corrected_at,
    )
    session.flush()


def _validate_allocations(action: ActionLog, allocations: Sequence[ExpirationAllocation]) -> None:
    _validate_allocation_total(allocations, action.quantity, "Expiration allocation quantities must match the action quantity.")


def _validate_allocation_total(allocations: Sequence[ExpirationAllocation], expected_quantity: int, message: str) -> None:
    if any(allocation.quantity < 0 for allocation in allocations):
        raise ValueError("Expiration allocation quantities must be non-negative.")
    if sum(allocation.quantity for allocation in allocations) != expected_quantity:
        raise ValueError(message)


def _apply_allocations_to_balances(
    session: Session,
    action: ActionLog,
    allocations: Sequence[ExpirationAllocation],
) -> None:
    known_allocations = [allocation for allocation in allocations if allocation.expires_on is not None]
    if action.operation_type == OperationType.COUNT and action.to_storage_id is not None:
        _replace_counted_balances(session, action, known_allocations)
        return
    if not known_allocations:
        return
    if action.to_storage_id is not None:
        _add_to_storage(session, action, action.to_storage_id, known_allocations)
    if action.from_storage_id is not None:
        _remove_from_storage(session, action, action.from_storage_id, known_allocations)


def _replace_counted_balances(
    session: Session,
    action: ActionLog,
    allocations: Sequence[ExpirationAllocation],
) -> None:
    if action.item_id is None or action.to_storage_id is None:
        raise ValueError("COUNT expiration allocations require an item and destination storage.")
    _replace_storage_expiration_balances(
        session,
        action.agency_id,
        action.item_id,
        action.to_storage_id,
        allocations,
        counted_at=action.time_scanned or utc_now(),
    )


def _replace_storage_expiration_balances(
    session: Session,
    agency_id: int,
    item_id: int,
    storage_id: int,
    allocations: Sequence[ExpirationAllocation],
    *,
    counted_at: datetime,
) -> None:
    session.execute(
        delete(InventoryExpirationBalance).where(
            InventoryExpirationBalance.agency_id == agency_id,
            InventoryExpirationBalance.item_id == item_id,
            InventoryExpirationBalance.storage_id == storage_id,
        )
    )
    now = utc_now()
    for allocation in allocations:
        if allocation.expires_on is None:
            continue
        session.add(
            InventoryExpirationBalance(
                agency_id=agency_id,
                item_id=item_id,
                storage_id=storage_id,
                expires_on=allocation.expires_on,
                quantity=allocation.quantity,
                last_counted_at=counted_at,
                updated_at=now,
            )
        )


def _add_to_storage(
    session: Session,
    action: ActionLog,
    storage_id: int,
    allocations: Sequence[ExpirationAllocation],
) -> None:
    rows = _balance_rows(session, action, storage_id, allocations)
    now = utc_now()
    for allocation in allocations:
        if allocation.expires_on is None:
            continue
        row = _ensure_balance_row(session, rows, action, storage_id, allocation.expires_on)
        row.quantity += allocation.quantity
        row.updated_at = now


def _remove_from_storage(
    session: Session,
    action: ActionLog,
    storage_id: int,
    allocations: Sequence[ExpirationAllocation],
) -> None:
    rows = _balance_rows(session, action, storage_id, allocations)
    now = utc_now()
    for allocation in allocations:
        if allocation.expires_on is None:
            continue
        row = _ensure_balance_row(session, rows, action, storage_id, allocation.expires_on)
        row.quantity -= allocation.quantity
        row.updated_at = now


def _balance_rows(
    session: Session,
    action: ActionLog,
    storage_id: int,
    allocations: Sequence[ExpirationAllocation],
) -> dict[date, InventoryExpirationBalance]:
    expires_on_values = sorted({allocation.expires_on for allocation in allocations if allocation.expires_on is not None})
    if not expires_on_values:
        return {}
    rows = session.execute(
        select(InventoryExpirationBalance).where(
            InventoryExpirationBalance.agency_id == action.agency_id,
            InventoryExpirationBalance.item_id == action.item_id,
            InventoryExpirationBalance.storage_id == storage_id,
            InventoryExpirationBalance.expires_on.in_(expires_on_values),
        )
    ).scalars()
    return {row.expires_on: row for row in rows}


def _ensure_balance_row(
    session: Session,
    rows: dict[date, InventoryExpirationBalance],
    action: ActionLog,
    storage_id: int,
    expires_on: date,
) -> InventoryExpirationBalance:
    row = rows.get(expires_on)
    if row is not None:
        return row
    if action.item_id is None:
        raise ValueError("Expiration balance rows require an item.")
    row = InventoryExpirationBalance(
        agency_id=action.agency_id,
        item_id=action.item_id,
        storage_id=storage_id,
        expires_on=expires_on,
        quantity=0,
        updated_at=utc_now(),
    )
    session.add(row)
    rows[expires_on] = row
    return row
