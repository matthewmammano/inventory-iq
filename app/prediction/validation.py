"""RESTOCK validation helpers."""

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import AgencyStorages
from app.inventory.constants import OperationType
from app.inventory.models import ActionLogs
from app.prediction.constants import RESTOCK_VALIDATION_HOURS
from app.prediction.segments import get_location_storage_ids
from app.shared.clock import utc_now

SESSION_REQUIRED_ERROR = "validate_restock requires an active session"


def validate_restock(
    agency_id: int,
    item_id: int,
    storage_id: int,
    session: Session | None = None,
) -> tuple[bool, str]:
    """A vendor restock requires fresh counts for every storage in the location."""
    if session is None:
        raise RuntimeError(SESSION_REQUIRED_ERROR)

    storage = (
        session.execute(
            select(AgencyStorages).where(
                AgencyStorages.id == storage_id,
                AgencyStorages.agency_id == agency_id,
            )
        )
        .scalars()
        .first()
    )
    if storage is None:
        return False, "Destination storage not found."

    return validate_location_restock(agency_id, item_id, storage.location_id, session)


def validate_location_restock(
    agency_id: int,
    item_id: int,
    agency_location_id: int,
    session: Session,
) -> tuple[bool, str]:
    stale_storage_ids = get_stale_count_storage_ids(agency_id, item_id, agency_location_id, session)
    if not stale_storage_ids:
        return True, ""

    msg = (
        "RESTOCK requires a full location count first. Count every storage in this "
        f"location within {RESTOCK_VALIDATION_HOURS} hours, then try the restock again."
    )
    return False, msg


def get_stale_count_storage_ids(
    agency_id: int,
    item_id: int,
    agency_location_id: int,
    session: Session,
) -> list[int]:
    storage_ids = get_location_storage_ids(session, agency_id, agency_location_id)
    if not storage_ids:
        return []

    cutoff = utc_now() - timedelta(hours=RESTOCK_VALIDATION_HOURS)
    fresh_rows = session.execute(
        select(ActionLogs.to_location_id)
        .where(
            ActionLogs.agency_id == agency_id,
            ActionLogs.item_id == item_id,
            ActionLogs.operation_type == OperationType.COUNT,
            ActionLogs.to_location_id.in_(storage_ids),
            ActionLogs.time_scanned >= cutoff,
        )
        .distinct()
    ).all()
    fresh_storage_ids = {row[0] for row in fresh_rows}
    return [storage_id for storage_id in storage_ids if storage_id not in fresh_storage_ids]
