"""Validated inventory mutations."""

from dataclasses import dataclass

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import Storage
from app.inventory.balance_service import sync_balances_for_actions
from app.inventory.location_state_service import sync_location_states_for_actions
from app.prediction.validation import validate_location_restock
from app.shared.clock import utc_now_naive
from app.shared.database import managed_session

from .constants import OperationType
from .errors import InventoryError
from .expiration_service import ExpirationAllocation, sync_expiration_alerts_after_save, sync_expiration_lines_for_action
from .models import ActionLog, Item


@dataclass(frozen=True, slots=True)
class MutationTarget:
    """Which item, how much, what kind of operation, and its storage route."""

    agency_id: int
    item_id: int
    quantity: int
    operation_type: OperationType
    from_storage: int | None
    to_storage: int | None


def inventory_operation(
    target: MutationTarget,
    admin_action: bool = False,
    expiration_allocations: list[ExpirationAllocation] | None = None,
    session: Session | None = None,
) -> ActionLog:
    """Execute one validated inventory operation and queue generated alerts."""
    from app.alerts.alert_service import record_action_log_alerts

    with managed_session(session) as db:
        item = _validate_operation(db, target)
        _touch_item_last_accessed(item)
        action = _add_action_log(db, target, admin_action)
        sync_balances_for_actions(db, [action])
        sync_expiration_lines_for_action(db, action, expiration_allocations or [])
        sync_location_states_for_actions(db, [action])
        record_action_log_alerts(db, [action])
        sync_expiration_alerts_after_save(db, target.agency_id, bool(expiration_allocations))
        logger.debug(
            "Inventory mutation applied",
            extra={
                "agency_id": target.agency_id,
                "action_log_id": action.id,
                "item_id": target.item_id,
                "operation_type": target.operation_type.value,
                "quantity": target.quantity,
                "from_storage_id": target.from_storage,
                "to_storage_id": target.to_storage,
                "admin_action": admin_action,
            },
        )
        return action


def _validate_operation(session: Session, target: MutationTarget) -> Item:
    if not isinstance(target.quantity, int) or target.quantity < 0:
        raise InventoryError("Quantity must be a non-negative number")
    if not target.operation_type.is_count and target.quantity == 0:
        raise InventoryError("Quantity must be at least 1 for non-count scans")

    item = _validate_item(session, target.agency_id, target.item_id)
    storages_by_id = _storage_rows(session, target.agency_id, target.from_storage, target.to_storage)
    _validate_operation_locations(session, target, storages_by_id)
    return item


def _ensure_known_storage(storages_by_id: dict[int, Storage], storage_id: int | None, label: str) -> None:
    """Raise if a resolved storage id isn't a real storage row for this agency."""
    if storage_id is not None and storage_id not in storages_by_id:
        raise InventoryError(f"{label} storage not found")


def _validate_operation_locations(session: Session, target: MutationTarget, storages_by_id: dict[int, Storage]) -> None:
    from_storage, to_storage = target.from_storage, target.to_storage
    if target.operation_type.is_count and (from_storage is not None or to_storage is None):
        raise InventoryError("COUNT requires one destination storage")
    if target.operation_type.is_restock:
        _validate_restock_location(session, target, storages_by_id)
    if target.operation_type.is_transfer:
        _validate_transfer_locations(from_storage, to_storage, storages_by_id)
    if target.operation_type.is_takeout and (from_storage is None or to_storage is not None):
        raise InventoryError("TAKEOUT requires one source storage")
    _ensure_known_storage(storages_by_id, from_storage, "Source")
    _ensure_known_storage(storages_by_id, to_storage, "Destination")


def _validate_restock_location(session: Session, target: MutationTarget, storages_by_id: dict[int, Storage]) -> None:
    if target.from_storage is not None or target.to_storage is None:
        raise InventoryError("RESTOCK requires one destination storage")
    to_storage_row = storages_by_id.get(target.to_storage)
    if to_storage_row is None:
        raise InventoryError("Destination storage not found")
    is_valid, message = validate_location_restock(target.agency_id, target.item_id, to_storage_row.location_id, session)
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
    _ensure_known_storage(storages_by_id, from_storage, "Source")
    _ensure_known_storage(storages_by_id, to_storage, "Destination")


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
    item.last_accessed = utc_now_naive()


def _add_action_log(session: Session, target: MutationTarget, admin_action: bool) -> ActionLog:
    action = ActionLog(
        agency_id=target.agency_id,
        item_id=target.item_id,
        operation_type=target.operation_type,
        from_storage_id=target.from_storage,
        to_storage_id=target.to_storage,
        quantity=target.quantity,
        admin_action=admin_action,
        time_scanned=utc_now_naive(),
    )
    session.add(action)
    session.flush()
    return action
