"""Validated inventory mutations."""

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import Storage
from app.inventory.balance_service import sync_balances_for_actions
from app.inventory.location_state_service import sync_location_states_for_actions
from app.prediction.validation import validate_location_restock
from app.shared.clock import utc_now
from app.shared.database import managed_session

from .constants import OperationType
from .errors import InventoryError
from .expiration_service import ExpirationAllocation, sync_expiration_lines_for_action
from .models import ActionLog, Item


def inventory_operation(
    agency_id: int,
    item_id: int,
    quantity: int,
    operation_type: OperationType,
    from_storage: int | None = None,
    to_storage: int | None = None,
    admin_action: bool = False,
    expiration_allocations: list[ExpirationAllocation] | None = None,
    session: Session | None = None,
) -> ActionLog:
    """Execute one validated inventory operation and queue generated alerts."""
    from app.alerts.alert_service import record_action_log_alerts, sync_expiration_audit_events

    with managed_session(session) as db:
        item = _validate_operation(db, agency_id, item_id, quantity, operation_type, from_storage, to_storage)
        _touch_item_last_accessed(item)
        action = _add_action_log(
            db,
            agency_id,
            item_id,
            quantity,
            operation_type,
            from_storage,
            to_storage,
            admin_action,
        )
        sync_balances_for_actions(db, [action])
        sync_expiration_lines_for_action(db, action, expiration_allocations or [])
        sync_location_states_for_actions(db, [action])
        record_action_log_alerts(db, [action])
        if any(allocation.expires_on is None for allocation in expiration_allocations or []):
            sync_expiration_audit_events(db, agency_id=agency_id)
        logger.debug(
            "Inventory mutation applied",
            extra={
                "agency_id": agency_id,
                "action_log_id": action.id,
                "item_id": item_id,
                "operation_type": operation_type.value,
                "quantity": quantity,
                "from_storage_id": from_storage,
                "to_storage_id": to_storage,
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
    from_storage: int | None,
    to_storage: int | None,
) -> Item:
    if not isinstance(quantity, int) or quantity < 0:
        raise InventoryError("Quantity must be a non-negative number")
    if not operation_type.is_count and quantity == 0:
        raise InventoryError("Quantity must be at least 1 for non-count scans")

    item = _validate_item(session, agency_id, item_id)
    storages_by_id = _storage_rows(session, agency_id, from_storage, to_storage)
    _validate_operation_locations(session, agency_id, item_id, operation_type, from_storage, to_storage, storages_by_id)
    return item


def _validate_operation_locations(
    session: Session,
    agency_id: int,
    item_id: int,
    operation_type: OperationType,
    from_storage: int | None,
    to_storage: int | None,
    storages_by_id: dict[int, Storage],
) -> None:
    if operation_type.is_count and (from_storage is not None or to_storage is None):
        raise InventoryError("COUNT requires one destination storage")
    if operation_type.is_restock:
        _validate_restock_location(session, agency_id, item_id, from_storage, to_storage, storages_by_id)
    if operation_type.is_transfer:
        _validate_transfer_locations(from_storage, to_storage, storages_by_id)
    if operation_type.is_takeout and (from_storage is None or to_storage is not None):
        raise InventoryError("TAKEOUT requires one source storage")
    if from_storage is not None and from_storage not in storages_by_id:
        raise InventoryError("Source storage not found")
    if to_storage is not None and to_storage not in storages_by_id:
        raise InventoryError("Destination storage not found")


def _validate_restock_location(
    session: Session,
    agency_id: int,
    item_id: int,
    from_storage: int | None,
    to_storage: int | None,
    storages_by_id: dict[int, Storage],
) -> None:
    if from_storage is not None or to_storage is None:
        raise InventoryError("RESTOCK requires one destination storage")
    to_storage_row = storages_by_id.get(to_storage)
    if to_storage_row is None:
        raise InventoryError("Destination storage not found")
    is_valid, message = validate_location_restock(agency_id, item_id, to_storage_row.location_id, session)
    if not is_valid:
        raise InventoryError(message)


def _validate_transfer_locations(
    from_storage: int | None,
    to_storage: int | None,
    storages_by_id: dict[int, Storage],
) -> None:
    if from_storage is None or to_storage is None:
        raise InventoryError("TRANSFER requires source and destination storages")
    if from_storage == to_storage:
        raise InventoryError("Cannot transfer to the same storage")
    from_storage_row = storages_by_id.get(from_storage)
    to_storage_row = storages_by_id.get(to_storage)
    if from_storage_row is None:
        raise InventoryError("Source storage not found")
    if to_storage_row is None:
        raise InventoryError("Destination storage not found")


def _validate_item(session: Session, agency_id: int, item_id: int) -> Item:
    item = session.get(Item, item_id)
    if item is None or item.agency_id != agency_id or not item.active:
        raise InventoryError("Item not found")
    return item


def _storage_rows(
    session: Session,
    agency_id: int,
    from_storage: int | None,
    to_storage: int | None,
) -> dict[int, Storage]:
    storage_ids = sorted({storage_id for storage_id in (from_storage, to_storage) if storage_id is not None})
    if not storage_ids:
        return {}
    rows = session.execute(
        select(Storage).where(
            Storage.agency_id == agency_id,
            Storage.id.in_(storage_ids),
        )
    ).scalars()
    return {storage.id: storage for storage in rows}


def _touch_item_last_accessed(item: Item) -> None:
    item.last_accessed = utc_now()


def _add_action_log(
    session: Session,
    agency_id: int,
    item_id: int,
    quantity: int,
    operation_type: OperationType,
    from_storage: int | None,
    to_storage: int | None,
    admin_action: bool,
) -> ActionLog:
    action = ActionLog(
        agency_id=agency_id,
        item_id=item_id,
        operation_type=operation_type,
        from_storage_id=from_storage,
        to_storage_id=to_storage,
        quantity=quantity,
        admin_action=admin_action,
        time_scanned=utc_now(),
    )
    session.add(action)
    session.flush()
    return action
