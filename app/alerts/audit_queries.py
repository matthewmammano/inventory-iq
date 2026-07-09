"""Read-only audit queries feeding the scheduled alert reconcile.

Repository layer for `alert_service`: flat DTO rows loaded from current state and
balances, with no ORM relationship traversal, so the service stays pure logic.
"""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.auth.models import Agency, Location, Storage
from app.inventory.location_state_service import ItemLocationKey
from app.inventory.models import InventoryExpirationBalance, InventoryItemLocationState, InventoryStorageBalance, Item


@dataclass(frozen=True)
class StateAuditRow:
    """Flat state row for the stale-count and rare-takeout audit."""

    agency_id: int
    count_last_days: int
    alert_rare_scan_days: int
    item_id: int
    item_name: str
    location_id: int
    location_name: str
    total_quantity: int
    last_counted_at: datetime | None
    last_takeout_at: datetime | None


@dataclass(frozen=True)
class ExpirationAuditRow:
    """Flat expiration row for the expired/expiring audit."""

    agency_id: int
    item_id: int
    item_name: str
    storage_id: int
    storage_name: str
    location_id: int
    location_name: str
    expires_on: date
    quantity: int
    notice_days: int


@dataclass(frozen=True)
class ExpirationCountAuditRow:
    """Flat quantity mismatch row for tracked expiration counts."""

    agency_id: int
    item_id: int
    item_name: str
    storage_id: int
    storage_name: str
    location_id: int
    location_name: str
    storage_quantity: int
    tracked_expiration_quantity: int


def load_state_audit_rows(
    session: Session,
    agency_id: int | None,
    item_location_keys: set[ItemLocationKey] | None = None,
) -> list[StateAuditRow]:
    stmt = (
        select(
            Agency.id,
            Agency.count_last_days,
            Agency.alert_rare_scan_days,
            Item.id,
            Item.name,
            Location.id,
            Location.name,
            InventoryItemLocationState.total_quantity,
            InventoryItemLocationState.last_counted_at,
            InventoryItemLocationState.last_takeout_at,
        )
        .join(Item, Item.agency_id == Agency.id)
        .join(Location, Location.agency_id == Agency.id)
        .join(
            InventoryItemLocationState,
            (InventoryItemLocationState.agency_id == Agency.id)
            & (InventoryItemLocationState.item_id == Item.id)
            & (InventoryItemLocationState.agency_location_id == Location.id),
        )
        .where(Agency.active.is_(True), Item.active.is_(True))
        .order_by(Agency.id, Item.id, Location.id)
    )
    if agency_id is not None:
        stmt = stmt.where(Agency.id == agency_id)
    if item_location_keys:
        stmt = stmt.where(
            Agency.id.in_({key.agency_id for key in item_location_keys}),
            Item.id.in_({key.item_id for key in item_location_keys}),
            Location.id.in_({key.agency_location_id for key in item_location_keys}),
        )

    rows = [
        StateAuditRow(
            agency_id=row[0],
            count_last_days=int(row[1] or 0),
            alert_rare_scan_days=int(row[2] or 0),
            item_id=row[3],
            item_name=row[4],
            location_id=row[5],
            location_name=row[6],
            total_quantity=int(row[7] or 0),
            last_counted_at=row[8],
            last_takeout_at=row[9],
        )
        for row in session.execute(stmt).all()
    ]
    if not item_location_keys:
        return rows
    return [row for row in rows if ItemLocationKey(row.agency_id, row.item_id, row.location_id) in item_location_keys]


def load_expiration_audit_rows(session: Session, agency_id: int | None) -> list[ExpirationAuditRow]:
    stmt = (
        select(
            Agency.id,
            Item.id,
            Item.name,
            Storage.id,
            Storage.name,
            Location.id,
            Location.name,
            InventoryExpirationBalance.expires_on,
            InventoryExpirationBalance.quantity,
            func.coalesce(Item.expiration_notice_days_override, Agency.expiration_notice_days),
        )
        .join(Item, Item.agency_id == Agency.id)
        .join(
            InventoryExpirationBalance,
            (InventoryExpirationBalance.agency_id == Agency.id) & (InventoryExpirationBalance.item_id == Item.id),
        )
        .join(Storage, Storage.id == InventoryExpirationBalance.storage_id)
        .join(Location, Location.id == Storage.location_id)
        .where(
            Agency.active.is_(True),
            Item.active.is_(True),
            Item.expiration_tracking_enabled.is_(True),
            InventoryExpirationBalance.quantity > 0,
        )
        .order_by(Agency.id, InventoryExpirationBalance.expires_on, Item.name, Location.name, Storage.name)
    )
    if agency_id is not None:
        stmt = stmt.where(Agency.id == agency_id)
    return [
        ExpirationAuditRow(
            agency_id=row[0],
            item_id=row[1],
            item_name=row[2],
            storage_id=row[3],
            storage_name=row[4],
            location_id=row[5],
            location_name=row[6],
            expires_on=row[7],
            quantity=int(row[8] or 0),
            notice_days=int(row[9] or 0),
        )
        for row in session.execute(stmt).all()
    ]


def load_expiration_count_audit_rows(session: Session, agency_id: int | None) -> list[ExpirationCountAuditRow]:
    storage_rows = _expiration_storage_totals(session, agency_id)
    expiration_totals = _expiration_tracked_totals(session, agency_id)
    rows: list[ExpirationCountAuditRow] = []
    for key in sorted(storage_rows.keys() | expiration_totals.keys()):
        base_row = storage_rows.get(key) or expiration_totals[key]
        storage_quantity = storage_rows[key].storage_quantity if key in storage_rows else 0
        tracked_quantity = expiration_totals[key].tracked_expiration_quantity if key in expiration_totals else 0
        if storage_quantity != tracked_quantity:
            rows.append(
                ExpirationCountAuditRow(
                    agency_id=base_row.agency_id,
                    item_id=base_row.item_id,
                    item_name=base_row.item_name,
                    storage_id=base_row.storage_id,
                    storage_name=base_row.storage_name,
                    location_id=base_row.location_id,
                    location_name=base_row.location_name,
                    storage_quantity=storage_quantity,
                    tracked_expiration_quantity=tracked_quantity,
                )
            )
    return rows


def _count_audit_row(row: Any, *, storage_quantity: int, tracked_expiration_quantity: int) -> ExpirationCountAuditRow:
    """Build a mismatch row from the shared 7 identity columns (agency..location_name)."""
    return ExpirationCountAuditRow(
        agency_id=row[0],
        item_id=row[1],
        item_name=row[2],
        storage_id=row[3],
        storage_name=row[4],
        location_id=row[5],
        location_name=row[6],
        storage_quantity=storage_quantity,
        tracked_expiration_quantity=tracked_expiration_quantity,
    )


def _expiration_totals_base() -> Select[Any]:
    """Identity columns + join/filter scaffold shared by both expiration-total queries."""
    return (
        select(Agency.id, Item.id, Item.name, Storage.id, Storage.name, Location.id, Location.name)
        .join(Item, Item.agency_id == Agency.id)
        .where(Agency.active.is_(True), Item.active.is_(True), Item.expiration_tracking_enabled.is_(True))
    )


def _expiration_storage_totals(session: Session, agency_id: int | None) -> dict[tuple[int, int, int], ExpirationCountAuditRow]:
    stmt = (
        _expiration_totals_base()
        .add_columns(InventoryStorageBalance.quantity)
        .join(InventoryStorageBalance, (InventoryStorageBalance.agency_id == Agency.id) & (InventoryStorageBalance.item_id == Item.id))
        .join(Storage, Storage.id == InventoryStorageBalance.storage_id)
        .join(Location, Location.id == Storage.location_id)
    )
    if agency_id is not None:
        stmt = stmt.where(Agency.id == agency_id)
    return {
        (row[0], row[1], row[3]): _count_audit_row(row, storage_quantity=int(row[7] or 0), tracked_expiration_quantity=0)
        for row in session.execute(stmt).all()
    }


def _expiration_tracked_totals(session: Session, agency_id: int | None) -> dict[tuple[int, int, int], ExpirationCountAuditRow]:
    stmt = (
        _expiration_totals_base()
        .add_columns(func.coalesce(func.sum(InventoryExpirationBalance.quantity), 0))
        .join(InventoryExpirationBalance, (InventoryExpirationBalance.agency_id == Agency.id) & (InventoryExpirationBalance.item_id == Item.id))
        .join(Storage, Storage.id == InventoryExpirationBalance.storage_id)
        .join(Location, Location.id == Storage.location_id)
        .group_by(Agency.id, Item.id, Item.name, Storage.id, Storage.name, Location.id, Location.name)
    )
    if agency_id is not None:
        stmt = stmt.where(Agency.id == agency_id)
    return {
        (row[0], row[1], row[3]): _count_audit_row(row, storage_quantity=0, tracked_expiration_quantity=int(row[7] or 0))
        for row in session.execute(stmt).all()
    }
