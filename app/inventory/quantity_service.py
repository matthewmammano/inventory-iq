"""
Centralized quantity calculations built directly from ActionLogs.

All quantities are computed on-demand; no cached ItemLocationQuantities table.
"""

from collections import defaultdict
from typing import TYPE_CHECKING, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.inventory.constants import OperationType

if TYPE_CHECKING:
    # ActionLogs only for type hints; inline import at runtime avoids circular dependency
    from app.inventory.models import ActionLogs


def _build_quantities_from_logs(logs: Iterable[ActionLogs]) -> dict[int, int]:
    """Fold ActionLogs into per-location quantities in time order."""
    quantities: dict[int, int] = defaultdict(int)

    for log in logs:
        to_loc = log.to_location_id
        from_loc = log.from_location_id

        if log.operation_type == OperationType.count and to_loc is not None:
            quantities[to_loc] = log.quantity_delta
            continue

        if to_loc is not None:
            quantities[to_loc] = quantities[to_loc] + log.quantity_delta
        if from_loc is not None:
            quantities[from_loc] = quantities[from_loc] - log.quantity_delta

    return dict(quantities)


def calculate_item_quantities(
    session: Session,
    user_id: int,
    item_id: int,
    *,
    location_id: int | None = None,
    exclude_action_ids: set[int] | None = None,
) -> dict[int, int]:
    """Compute current quantities for an item across locations from ActionLogs."""
    from app.inventory.models import (
        ActionLogs,
    )  # Inline import avoids circular dependency

    stmt = (
        select(ActionLogs)
        .where(ActionLogs.user_id == user_id, ActionLogs.item_id == item_id)
        .order_by(ActionLogs.time_scanned.asc(), ActionLogs.id.asc())
    )

    if exclude_action_ids:
        stmt = stmt.where(~ActionLogs.id.in_(exclude_action_ids))

    logs = session.execute(stmt).scalars().all()
    quantities = _build_quantities_from_logs(logs)

    if location_id is not None:
        return {location_id: quantities.get(location_id, 0)}

    return quantities


def apply_action_to_quantities(
    quantities: dict[int, int], action: ActionLogs
) -> dict[int, int]:
    """Apply a single action's delta to an existing quantity map."""
    updated = dict(quantities)
    to_loc = action.to_location_id
    from_loc = action.from_location_id

    if action.operation_type == OperationType.count and to_loc is not None:
        updated[to_loc] = action.quantity_delta
        return updated

    if to_loc is not None:
        updated[to_loc] = updated.get(to_loc, 0) + action.quantity_delta
    if from_loc is not None:
        updated[from_loc] = updated.get(from_loc, 0) - action.quantity_delta

    return updated
