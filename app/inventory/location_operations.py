"""Bulk location count and vendor restock operations."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import AgencyStorages
from app.inventory.balance_service import build_location_quantity_rows, sync_balances_for_actions
from app.inventory.constants import OperationType
from app.inventory.models import ActionLogs, Items
from app.shared.clock import utc_now


def get_location_storages(
    session: Session,
    agency_id: int,
    agency_location_id: int,
) -> list[AgencyStorages]:
    return list(
        session.execute(
            select(AgencyStorages)
            .where(
                AgencyStorages.agency_id == agency_id,
                AgencyStorages.location_id == agency_location_id,
            )
            .order_by(AgencyStorages.name)
        )
        .scalars()
        .all()
    )


def build_location_count_rows(
    session: Session,
    agency_id: int,
    agency_location_id: int,
) -> tuple[list[Items], list[AgencyStorages], dict[tuple[int, int], int]]:
    return build_location_quantity_rows(session, agency_id, agency_location_id)


def save_location_count(
    session: Session,
    agency_id: int,
    agency_location_id: int,
    quantities: dict[tuple[int, int], int],
) -> list[ActionLogs]:
    storages = get_location_storages(session, agency_id, agency_location_id)
    storage_ids = {storage.id for storage in storages}
    item_ids = _active_item_ids(session, agency_id)
    now = utc_now()
    logs = [
        ActionLogs(
            agency_id=agency_id,
            item_id=item_id,
            operation_type=OperationType.COUNT,
            from_location_id=None,
            to_location_id=storage_id,
            quantity_delta=max(quantity, 0),
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
) -> list[ActionLogs]:
    storages = get_location_storages(session, agency_id, agency_location_id)
    storage_ids = {storage.id for storage in storages}
    item_ids = _active_item_ids(session, agency_id)
    now = utc_now()
    logs = [
        ActionLogs(
            agency_id=agency_id,
            item_id=item_id,
            operation_type=OperationType.RESTOCK,
            from_location_id=None,
            to_location_id=storage_id,
            quantity_delta=quantity,
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
    return set(session.execute(select(Items.id).where(Items.agency_id == agency_id, Items.active.is_(True))).scalars())
