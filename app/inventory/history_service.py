"""Shared action history queries for admin views and exports."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload

from app.auth.models import Storage
from app.inventory.location_operations import get_location_storages
from app.inventory.models import ActionLog

HISTORY_REPORT_LIMIT = 5000


@dataclass(frozen=True, slots=True)
class HistoryLogQuery:
    """Page window and optional UTC date bounds for filtering action history."""

    page: int
    page_size: int
    start_utc: datetime | None = None
    end_utc: datetime | None = None


def list_history_logs(
    session: Session,
    agency_id: int,
    agency_location_id: int | None,
    query: HistoryLogQuery,
) -> tuple[list[ActionLog], bool]:
    """Return one page of action history for an agency and optional location scope."""
    stmt = (
        select(ActionLog)
        .options(
            joinedload(ActionLog.item),
            joinedload(ActionLog.from_storage).joinedload(Storage.location),
            joinedload(ActionLog.to_storage).joinedload(Storage.location),
            joinedload(ActionLog.expiration_lines),
        )
        .where(ActionLog.agency_id == agency_id)
    )
    if agency_location_id is not None:
        storage_ids = [storage.id for storage in get_location_storages(session, agency_id, agency_location_id)]
        stmt = stmt.where(
            or_(
                ActionLog.from_storage_id.in_(storage_ids),
                ActionLog.to_storage_id.in_(storage_ids),
            )
            if storage_ids
            else ActionLog.id == -1
        )
    if query.start_utc is not None:
        stmt = stmt.where(ActionLog.time_scanned >= query.start_utc)
    if query.end_utc is not None:
        stmt = stmt.where(ActionLog.time_scanned < query.end_utc)
    rows = list(
        session.execute(stmt.order_by(ActionLog.id.desc()).offset((query.page - 1) * query.page_size).limit(query.page_size + 1))
        .unique()
        .scalars()
        .all()
    )
    return rows[: query.page_size], len(rows) > query.page_size
