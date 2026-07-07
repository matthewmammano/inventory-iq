"""Inventory quantity calculations from action logs."""

from collections import defaultdict
from datetime import timedelta

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.shared.clock import utc_now
from app.shared.database import managed_session

from .balance_service import get_item_quantities, has_balance_rows
from .constants import OperationType
from .models import ActionLog


def get_recent_admin_count(
    agency_id: int,
    item_id: int,
    storage_id: int,
    hours_back: int,
    session: Session | None = None,
) -> ActionLog | None:
    with managed_session(session) as db:
        cutoff = utc_now() - timedelta(hours=hours_back)
        stmt = (
            select(ActionLog)
            .where(
                ActionLog.agency_id == agency_id,
                ActionLog.item_id == item_id,
                ActionLog.to_storage_id == storage_id,
                ActionLog.operation_type == OperationType.COUNT,
                ActionLog.admin_action.is_(True),
                ActionLog.time_scanned >= cutoff,
            )
            .order_by(ActionLog.time_scanned.desc())
        )
        return db.execute(stmt).scalars().first()


def has_item_count(
    session: Session,
    agency_id: int,
    item_id: int,
) -> bool:
    """Return whether an item has ever had a COUNT operation."""
    return bool(
        session.scalar(
            select(
                exists().where(
                    ActionLog.agency_id == agency_id,
                    ActionLog.item_id == item_id,
                    ActionLog.operation_type == OperationType.COUNT,
                )
            )
        )
    )


def calculate_item_quantities(
    session: Session,
    agency_id: int,
    item_id: int,
    *,
    location_id: int | None = None,
    exclude_action_ids: set[int] | None = None,
) -> dict[int, int]:
    if not exclude_action_ids and has_balance_rows(session, agency_id, item_id):
        quantities = get_item_quantities(session, agency_id, item_id)
        if location_id is not None:
            return {location_id: quantities.get(location_id, 0)}
        return quantities

    return _calculate_item_quantities_from_logs(
        session,
        agency_id,
        item_id,
        location_id=location_id,
        exclude_action_ids=exclude_action_ids,
    )


def _calculate_item_quantities_from_logs(
    session: Session,
    agency_id: int,
    item_id: int,
    *,
    location_id: int | None = None,
    exclude_action_ids: set[int] | None = None,
) -> dict[int, int]:
    stmt = (
        select(ActionLog)
        .where(ActionLog.agency_id == agency_id, ActionLog.item_id == item_id)
        .order_by(ActionLog.time_scanned.asc(), ActionLog.id.asc())
    )
    if exclude_action_ids:
        stmt = stmt.where(ActionLog.id.notin_(exclude_action_ids))

    quantities = _build_quantities_from_logs(list(session.execute(stmt).scalars().all()))
    if location_id is not None:
        return {location_id: quantities.get(location_id, 0)}
    return quantities


def apply_action_to_quantities(quantities: dict[int, int], action: ActionLog) -> dict[int, int]:
    updated = dict(quantities)
    to_storage_id = action.to_storage_id
    from_storage_id = action.from_storage_id

    if action.is_count and to_storage_id is not None:
        updated[to_storage_id] = action.quantity
        return updated
    if to_storage_id is not None:
        updated[to_storage_id] = updated.get(to_storage_id, 0) + action.quantity
    if from_storage_id is not None:
        updated[from_storage_id] = updated.get(from_storage_id, 0) - action.quantity
    return updated


def _build_quantities_from_logs(logs: list[ActionLog]) -> dict[int, int]:
    quantities: dict[int, int] = defaultdict(int)
    for log in logs:
        if log.is_count and log.to_storage_id is not None:
            quantities[log.to_storage_id] = log.quantity
            continue
        if log.to_storage_id is not None:
            quantities[log.to_storage_id] += log.quantity
        if log.from_storage_id is not None:
            quantities[log.from_storage_id] -= log.quantity
    return dict(quantities)
