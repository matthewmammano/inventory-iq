"""RESTOCK validation helpers."""

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import Agency, Storage
from app.inventory.balance_service import get_required_count_storage_ids
from app.prediction.constants import RESTOCK_VALIDATION_DAYS
from app.shared.clock import utc_now_naive

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
            select(Storage).where(
                Storage.id == storage_id,
                Storage.agency_id == agency_id,
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
    """Require every storage in a location to have a fresh count before restock."""
    stale_storage_ids = get_stale_count_storage_ids(agency_id, item_id, agency_location_id, session)
    if not stale_storage_ids:
        return True, ""

    msg = (
        "RESTOCK requires a full location count first. Count every storage in this "
        f"location within {_restock_validation_days(agency_id, session)} days, "
        "then try the restock again."
    )
    return False, msg


def get_stale_count_storage_ids(
    agency_id: int,
    item_id: int,
    agency_location_id: int,
    session: Session,
) -> list[int]:
    """Return storage IDs missing a recent count for restock validation."""
    cutoff = utc_now_naive() - timedelta(days=_restock_validation_days(agency_id, session))
    return sorted(get_required_count_storage_ids(session, agency_id, agency_location_id, [item_id], cutoff).get(item_id, set()))


def _restock_validation_days(agency_id: int, session: Session) -> int:
    agency = session.get(Agency, agency_id)
    return int(agency.count_last_days if agency and agency.count_last_days else RESTOCK_VALIDATION_DAYS)
