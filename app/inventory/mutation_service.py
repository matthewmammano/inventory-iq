"""Validated inventory mutations."""

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import AgencyStorages
from app.inventory.balance_service import sync_balances_for_actions
from app.prediction.validation import validate_location_restock
from app.shared.clock import utc_now
from app.shared.database import managed_session

from .constants import OperationType
from .errors import InventoryError
from .models import ActionLogs, Items


def inventory_operation(
    agency_id: int,
    item_id: int,
    quantity: int,
    operation_type: OperationType,
    from_location: int | None = None,
    to_location: int | None = None,
    admin_action: bool = False,
    session: Session | None = None,
) -> ActionLogs:
    """Execute one validated inventory operation and queue generated alerts."""
    from app.alerts.alert_service import record_action_log_alerts

    with managed_session(session) as db:
        item = _validate_operation(db, agency_id, item_id, quantity, operation_type, from_location, to_location)
        _touch_item_last_accessed(item)
        action = _add_action_log(
            db,
            agency_id,
            item_id,
            quantity,
            operation_type,
            from_location,
            to_location,
            admin_action,
        )
        sync_balances_for_actions(db, [action])
        record_action_log_alerts(db, [action])
        logger.debug(
            "Inventory mutation applied",
            extra={
                "agency_id": agency_id,
                "action_log_id": action.id,
                "item_id": item_id,
                "operation_type": operation_type.value,
                "quantity": quantity,
                "from_storage_id": from_location,
                "to_storage_id": to_location,
                "admin_action": admin_action,
            },
        )
        return action


def _validate_operation(
    session: Session,
    agency_id: int,
    item_id: int,
    quantity: int,
    operation_type: OperationType,
    from_location: int | None,
    to_location: int | None,
) -> Items:
    if not isinstance(quantity, int) or quantity < 0:
        raise InventoryError("Quantity must be a non-negative number")
    if operation_type != OperationType.COUNT and quantity == 0:
        raise InventoryError("Quantity must be at least 1 for non-count scans")

    item = _validate_item(session, agency_id, item_id)
    storages_by_id = _storage_rows(session, agency_id, from_location, to_location)
    _validate_operation_locations(session, agency_id, item_id, operation_type, from_location, to_location, storages_by_id)
    return item


def _validate_operation_locations(
    session: Session,
    agency_id: int,
    item_id: int,
    operation_type: OperationType,
    from_location: int | None,
    to_location: int | None,
    storages_by_id: dict[int, AgencyStorages],
) -> None:
    if operation_type == OperationType.COUNT and (from_location is not None or to_location is None):
        raise InventoryError("COUNT requires one destination storage")
    if operation_type == OperationType.RESTOCK:
        _validate_restock_location(session, agency_id, item_id, from_location, to_location, storages_by_id)
    if operation_type == OperationType.TRANSFER:
        _validate_transfer_locations(from_location, to_location, storages_by_id)
    if operation_type == OperationType.TAKEOUT and (from_location is None or to_location is not None):
        raise InventoryError("TAKEOUT requires one source storage")
    if from_location is not None and from_location not in storages_by_id:
        raise InventoryError("Source storage not found")
    if to_location is not None and to_location not in storages_by_id:
        raise InventoryError("Destination storage not found")


def _validate_restock_location(
    session: Session,
    agency_id: int,
    item_id: int,
    from_location: int | None,
    to_location: int | None,
    storages_by_id: dict[int, AgencyStorages],
) -> None:
    if from_location is not None or to_location is None:
        raise InventoryError("RESTOCK requires one destination storage")
    to_storage = storages_by_id.get(to_location)
    if to_storage is None:
        raise InventoryError("Destination storage not found")
    is_valid, message = validate_location_restock(agency_id, item_id, to_storage.location_id, session)
    if not is_valid:
        raise InventoryError(message)


def _validate_transfer_locations(
    from_location: int | None,
    to_location: int | None,
    storages_by_id: dict[int, AgencyStorages],
) -> None:
    if from_location is None or to_location is None:
        raise InventoryError("TRANSFER requires source and destination storages")
    if from_location == to_location:
        raise InventoryError("Cannot transfer to the same storage")
    from_storage = storages_by_id.get(from_location)
    to_storage = storages_by_id.get(to_location)
    if from_storage is None:
        raise InventoryError("Source storage not found")
    if to_storage is None:
        raise InventoryError("Destination storage not found")
    if from_storage.location_id != to_storage.location_id:
        raise InventoryError("Cannot transfer across locations")


def _validate_item(session: Session, agency_id: int, item_id: int) -> Items:
    item = session.get(Items, item_id)
    if item is None or item.agency_id != agency_id or not item.active:
        raise InventoryError("Item not found")
    return item


def _storage_rows(
    session: Session,
    agency_id: int,
    from_location: int | None,
    to_location: int | None,
) -> dict[int, AgencyStorages]:
    storage_ids = sorted({storage_id for storage_id in (from_location, to_location) if storage_id is not None})
    if not storage_ids:
        return {}
    rows = session.execute(
        select(AgencyStorages).where(
            AgencyStorages.agency_id == agency_id,
            AgencyStorages.id.in_(storage_ids),
        )
    ).scalars()
    return {storage.id: storage for storage in rows}


def _touch_item_last_accessed(item: Items) -> None:
    item.last_accessed = utc_now()


def _add_action_log(
    session: Session,
    agency_id: int,
    item_id: int,
    quantity: int,
    operation_type: OperationType,
    from_location: int | None,
    to_location: int | None,
    admin_action: bool,
) -> ActionLogs:
    action = ActionLogs(
        agency_id=agency_id,
        item_id=item_id,
        operation_type=operation_type,
        from_location_id=from_location,
        to_location_id=to_location,
        quantity_delta=quantity,
        admin_action=admin_action,
        time_scanned=utc_now(),
    )
    session.add(action)
    session.flush()
    return action
