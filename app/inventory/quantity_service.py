"""Inventory quantity calculations from action logs."""

from collections import defaultdict
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.shared.clock import utc_now
from app.shared.database import managed_session

from .constants import OperationType
from .models import ActionLogs


def get_recent_admin_count(
    agency_id: int,
    item_id: int,
    storage_id: int,
    hours_back: int,
    session: Session | None = None,
) -> ActionLogs | None:
    with managed_session(session) as db:
        cutoff = utc_now() - timedelta(hours=hours_back)
        stmt = (
            select(ActionLogs)
            .where(
                ActionLogs.agency_id == agency_id,
                ActionLogs.item_id == item_id,
                ActionLogs.to_location_id == storage_id,
                ActionLogs.operation_type == OperationType.COUNT,
                ActionLogs.admin_action.is_(True),
                ActionLogs.time_scanned >= cutoff,
            )
            .order_by(ActionLogs.time_scanned.desc())
        )
        return db.execute(stmt).scalars().first()


def calculate_item_quantities(
    session: Session,
    agency_id: int,
    item_id: int,
    *,
    location_id: int | None = None,
    exclude_action_ids: set[int] | None = None,
) -> dict[int, int]:
    stmt = (
        select(ActionLogs)
        .where(ActionLogs.agency_id == agency_id, ActionLogs.item_id == item_id)
        .order_by(ActionLogs.time_scanned.asc(), ActionLogs.id.asc())
    )
    if exclude_action_ids:
        stmt = stmt.where(ActionLogs.id.notin_(exclude_action_ids))

    quantities = _build_quantities_from_logs(list(session.execute(stmt).scalars().all()))
    if location_id is not None:
        return {location_id: quantities.get(location_id, 0)}
    return quantities


def apply_action_to_quantities(quantities: dict[int, int], action: ActionLogs) -> dict[int, int]:
    updated = dict(quantities)
    to_storage_id = action.to_location_id
    from_storage_id = action.from_location_id

    if action.operation_type == OperationType.COUNT and to_storage_id is not None:
        updated[to_storage_id] = action.quantity_delta
        return updated
    if to_storage_id is not None:
        updated[to_storage_id] = updated.get(to_storage_id, 0) + action.quantity_delta
    if from_storage_id is not None:
        updated[from_storage_id] = updated.get(from_storage_id, 0) - action.quantity_delta
    return updated


def _build_quantities_from_logs(logs: list[ActionLogs]) -> dict[int, int]:
    quantities: dict[int, int] = defaultdict(int)
    for log in logs:
        if log.operation_type == OperationType.COUNT and log.to_location_id is not None:
            quantities[log.to_location_id] = log.quantity_delta
            continue
        if log.to_location_id is not None:
            quantities[log.to_location_id] += log.quantity_delta
        if log.from_location_id is not None:
            quantities[log.from_location_id] -= log.quantity_delta
    return dict(quantities)
