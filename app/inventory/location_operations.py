"""Bulk location count and vendor restock operations."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import Storage
from app.inventory.balance_service import build_location_quantity_rows, sync_balances_for_actions
from app.inventory.constants import OperationType
from app.inventory.models import ActionLog, Item
from app.shared.clock import utc_now_naive


def get_location_storages(
    session: Session,
    agency_id: int,
    agency_location_id: int,
) -> list[Storage]:
    return list(
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


def get_storages_for_locations(
    session: Session,
    agency_id: int,
    agency_location_ids: list[int],
) -> list[Storage]:
    """Return storages for a set of locations, e.g. a recipient's location filter."""
    return list(
        session.execute(
            select(Storage)
            .where(
                Storage.agency_id == agency_id,
                Storage.location_id.in_(agency_location_ids),
            )
            .order_by(Storage.name)
        )
        .scalars()
        .all()
    )


def build_location_count_rows(
    session: Session,
    agency_id: int,
    agency_location_id: int,
    *,
    include_secondary_upcs: bool = False,
) -> tuple[list[Item], list[Storage], dict[tuple[int, int], int]]:
    return build_location_quantity_rows(session, agency_id, agency_location_id, include_secondary_upcs=include_secondary_upcs)


def save_location_count(
    session: Session,
    agency_id: int,
    agency_location_id: int,
    quantities: dict[tuple[int, int], int],
) -> list[ActionLog]:
    storages = get_location_storages(session, agency_id, agency_location_id)
    storage_ids = {storage.id for storage in storages}
    item_ids = _active_item_ids(session, agency_id)
    now = utc_now_naive()
    logs = [
        ActionLog(
            agency_id=agency_id,
            item_id=item_id,
            operation_type=OperationType.COUNT,
            from_storage_id=None,
            to_storage_id=storage_id,
            quantity=max(quantity, 0),
            admin_action=True,
            time_scanned=now,
        )
        for (item_id, storage_id), quantity in quantities.items()
        if item_id in item_ids and storage_id in storage_ids
    ]
    session.add_all(logs)
    session.flush()
    sync_balances_for_actions(session, logs)
    return logs


def save_location_restock(
    session: Session,
    agency_id: int,
    agency_location_id: int,
    quantities: dict[tuple[int, int], int],
) -> list[ActionLog]:
    storages = get_location_storages(session, agency_id, agency_location_id)
    storage_ids = {storage.id for storage in storages}
    item_ids = _active_item_ids(session, agency_id)
    now = utc_now_naive()
    logs = [
        ActionLog(
            agency_id=agency_id,
            item_id=item_id,
            operation_type=OperationType.RESTOCK,
            from_storage_id=None,
            to_storage_id=storage_id,
            quantity=quantity,
            admin_action=True,
            time_scanned=now,
        )
        for (item_id, storage_id), quantity in quantities.items()
        if item_id in item_ids and storage_id in storage_ids and quantity > 0
    ]
    session.add_all(logs)
    session.flush()
    sync_balances_for_actions(session, logs)
    return logs


def _active_item_ids(session: Session, agency_id: int) -> set[int]:
    return set(session.execute(select(Item.id).where(Item.agency_id == agency_id, Item.active.is_(True))).scalars())
