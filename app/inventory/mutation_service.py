"""Validated inventory mutations."""

from loguru import logger
from sqlalchemy.orm import Session

from app.auth.queries import get_storage
from app.prediction.estimator import get_location_item_quantity
from app.prediction.validation import validate_restock
from app.shared.clock import utc_now
from app.shared.database import get_session

from .constants import OperationType
from .errors import InventoryError
from .item_queries import get_item
from .models import ActionLogs


def inventory_operation(
    agency_id: int,
    item_id: int,
    quantity: int,
    operation_type: OperationType,
    from_location: int | None = None,
    to_location: int | None = None,
    admin_action: bool = False,
) -> None:
    """Execute one validated inventory operation and queue generated alerts."""
    from app.alerts.alert_service import record_action_log_alerts

    with get_session() as db:
        _validate_operation(
            db, agency_id, item_id, quantity, operation_type, from_location, to_location
        )
        quantity_snapshots = _quantity_snapshots(db, agency_id, item_id, from_location, to_location)
        _touch_item_last_accessed(db, item_id)
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
        record_action_log_alerts(
            db,
            [action],
            _updated_snapshots(db, agency_id, item_id, quantity_snapshots),
        )
        db.commit()

        logger.info("{}: item={} qty={}", operation_type.value, item_id, quantity)


def _validate_operation(
    session: Session,
    agency_id: int,
    item_id: int,
    quantity: int,
    operation_type: OperationType,
    from_location: int | None,
    to_location: int | None,
) -> None:
    if not isinstance(quantity, int) or quantity < 0:
        raise InventoryError("Quantity must be a non-negative number")
    if operation_type in (OperationType.TRANSFER, OperationType.TAKEOUT) and quantity == 0:
        raise InventoryError("Cannot transfer or remove zero items")

    _validate_operation_locations(
        session, agency_id, item_id, operation_type, from_location, to_location
    )
    _validate_item(session, agency_id, item_id)

    if from_location is not None and not get_storage(from_location, agency_id, session):
        raise InventoryError("Source storage not found")
    if to_location is not None and not get_storage(to_location, agency_id, session):
        raise InventoryError("Destination storage not found")


def _validate_operation_locations(
    session: Session,
    agency_id: int,
    item_id: int,
    operation_type: OperationType,
    from_location: int | None,
    to_location: int | None,
) -> None:
    if operation_type == OperationType.COUNT and (from_location is not None or to_location is None):
        raise InventoryError("COUNT requires one destination storage")
    if operation_type == OperationType.RESTOCK:
        _validate_restock_location(session, agency_id, item_id, from_location, to_location)
    if operation_type == OperationType.TRANSFER:
        _validate_transfer_locations(from_location, to_location)
    if operation_type == OperationType.TAKEOUT and (
        from_location is None or to_location is not None
    ):
        raise InventoryError("TAKEOUT requires one source storage")


def _validate_restock_location(
    session: Session,
    agency_id: int,
    item_id: int,
    from_location: int | None,
    to_location: int | None,
) -> None:
    if from_location is not None or to_location is None:
        raise InventoryError("RESTOCK requires one destination storage")
    is_valid, message = validate_restock(agency_id, item_id, to_location, session)
    if not is_valid:
        raise InventoryError(message)


def _validate_transfer_locations(from_location: int | None, to_location: int | None) -> None:
    if from_location is None or to_location is None:
        raise InventoryError("TRANSFER requires source and destination storages")
    if from_location == to_location:
        raise InventoryError("Cannot transfer to the same storage")


def _validate_item(session: Session, agency_id: int, item_id: int) -> None:
    item = get_item(item_id, session)
    if not item or item.agency_id != agency_id:
        raise InventoryError("Item not found")
    if not item.active:
        raise InventoryError("Item is inactive")


def _touch_item_last_accessed(session: Session, item_id: int) -> None:
    item = get_item(item_id, session)
    if item:
        item.last_accessed = utc_now()


def _quantity_snapshots(
    session: Session,
    agency_id: int,
    item_id: int,
    from_location: int | None,
    to_location: int | None,
) -> dict[int, int]:
    location_ids = {
        storage.location_id
        for storage in (
            get_storage(from_location, agency_id, session) if from_location else None,
            get_storage(to_location, agency_id, session) if to_location else None,
        )
        if storage is not None
    }
    return {
        location_id: get_location_item_quantity(session, agency_id, item_id, location_id)
        for location_id in location_ids
    }


def _updated_snapshots(
    session: Session,
    agency_id: int,
    item_id: int,
    previous_totals: dict[int, int],
) -> dict[tuple[int, int, int], tuple[int, int]]:
    return {
        (agency_id, item_id, location_id): (
            before_total,
            get_location_item_quantity(session, agency_id, item_id, location_id),
        )
        for location_id, before_total in previous_totals.items()
    }


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
