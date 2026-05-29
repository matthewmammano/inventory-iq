"""Bulk location count and vendor restock operations."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import AgencyStorages
from app.inventory.constants import OperationType
from app.inventory.item_queries import list_items
from app.inventory.models import ActionLogs, Items
from app.inventory.quantity_service import calculate_item_quantities
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
    items = list_items(agency_id, session=session)
    storages = get_location_storages(session, agency_id, agency_location_id)
    storage_ids = {storage.id for storage in storages}
    counts: dict[tuple[int, int], int] = {}
    for item in items:
        quantities = calculate_item_quantities(session, agency_id, item.id)
        for storage_id in storage_ids:
            counts[(item.id, storage_id)] = int(quantities.get(storage_id, 0))
    return items, storages, counts


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
    return logs


def parse_quantity_grid(
    form,
    *,
    prefix: str = "qty_",
    skip_blank: bool = False,
) -> dict[tuple[int, int], int]:
    quantities: dict[tuple[int, int], int] = {}
    for key, value in form.items():
        if not key.startswith(prefix) or (skip_blank and value == ""):
            continue
        try:
            item_id, storage_id = key.removeprefix(prefix).split("_", maxsplit=1)
            quantities[(int(item_id), int(storage_id))] = max(int(value or 0), 0)
        except (TypeError, ValueError):
            continue
    return quantities


def _active_item_ids(session: Session, agency_id: int) -> set[int]:
    return set(
        session.execute(
            select(Items.id).where(Items.agency_id == agency_id, Items.active.is_(True))
        ).scalars()
    )
