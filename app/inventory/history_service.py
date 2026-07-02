"""Shared action history queries for admin views and exports."""

from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload

from app.inventory.location_operations import get_location_storages
from app.inventory.models import ActionLogs

HISTORY_REPORT_LIMIT = 5000


def list_history_logs(
    session: Session,
    agency_id: int,
    agency_location_id: int | None,
    page: int,
    page_size: int,
    start_utc: datetime | None = None,
    end_utc: datetime | None = None,
) -> tuple[list[ActionLogs], bool]:
    """Return one page of action history for an agency and optional location scope."""
    stmt = (
        select(ActionLogs)
        .options(
            joinedload(ActionLogs.item),
            joinedload(ActionLogs.from_location),
            joinedload(ActionLogs.to_location),
        )
        .where(ActionLogs.agency_id == agency_id)
    )
    if agency_location_id is not None:
        storage_ids = [storage.id for storage in get_location_storages(session, agency_id, agency_location_id)]
        stmt = stmt.where(
            or_(
                ActionLogs.from_location_id.in_(storage_ids),
                ActionLogs.to_location_id.in_(storage_ids),
            )
            if storage_ids
            else ActionLogs.id == -1
        )
    if start_utc is not None:
        stmt = stmt.where(ActionLogs.time_scanned >= start_utc)
    if end_utc is not None:
        stmt = stmt.where(ActionLogs.time_scanned < end_utc)
    rows = list(session.execute(stmt.order_by(ActionLogs.id.desc()).offset((page - 1) * page_size).limit(page_size + 1)).scalars().all())
    return rows[:page_size], len(rows) > page_size
