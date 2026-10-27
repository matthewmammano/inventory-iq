"""Shared action history queries for admin views and exports."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Select, asc, desc, func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.auth.models import Storage
from app.inventory.location_operations import get_location_storages
from app.inventory.models import ActionLog, Item

HISTORY_REPORT_LIMIT = 5000
HISTORY_PAGE_SIZE = 50


@dataclass(frozen=True, slots=True)
class HistoryColumn:
    """One history heading; an empty sort key means the column cannot be ordered in SQL."""

    label: str
    sort_key: str = ""


HISTORY_COLUMNS: tuple[HistoryColumn, ...] = (
    HistoryColumn("Time", "time"),
    HistoryColumn("Item", "item"),
    HistoryColumn("Type", "type"),
    HistoryColumn("Qty", "qty"),
    HistoryColumn("From"),
    HistoryColumn("To"),
    HistoryColumn("Admin?", "admin"),
    HistoryColumn("Expirations"),
)

HISTORY_SORT_EXPRESSIONS = {
    "time": ActionLog.time_scanned,
    "item": Item.name,
    "type": ActionLog.operation_type,
    "qty": ActionLog.quantity,
    "admin": ActionLog.admin_action,
}

DEFAULT_HISTORY_SORT_KEY = "time"


def normalize_history_sort_key(sort_key: str) -> str:
    return sort_key if sort_key in HISTORY_SORT_EXPRESSIONS else DEFAULT_HISTORY_SORT_KEY


@dataclass(frozen=True, slots=True)
class HistoryLogQuery:
    """Page window and optional UTC date bounds for filtering action history."""

    page: int
    page_size: int
    start_utc: datetime | None = None
    end_utc: datetime | None = None
    sort_key: str = DEFAULT_HISTORY_SORT_KEY
    descending: bool = True

    @property
    def sort_expression(self) -> Any:
        return HISTORY_SORT_EXPRESSIONS[self.sort_key]


def _scoped_history_select(
    session: Session,
    agency_id: int,
    agency_location_id: int | None,
    query: HistoryLogQuery,
) -> Select[ActionLog]:
    """Action history narrowed to one agency, optional location scope, and optional date bounds."""
    stmt = select(ActionLog).where(ActionLog.agency_id == agency_id)
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
    return stmt


def count_history_logs(
    session: Session,
    agency_id: int,
    agency_location_id: int | None,
    query: HistoryLogQuery,
) -> int:
    """Total matching rows, so a paginated view can show how many pages exist."""
    stmt = _scoped_history_select(session, agency_id, agency_location_id, query)
    return session.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()


def list_history_logs(
    session: Session,
    agency_id: int,
    agency_location_id: int | None,
    query: HistoryLogQuery,
) -> list[ActionLog]:
    """Return one page of action history for an agency and optional location scope."""
    ordering = desc(query.sort_expression) if query.descending else asc(query.sort_expression)
    stmt = (
        _scoped_history_select(session, agency_id, agency_location_id, query)
        .options(
            joinedload(ActionLog.item),
            joinedload(ActionLog.from_storage).joinedload(Storage.location),
            joinedload(ActionLog.to_storage).joinedload(Storage.location),
            joinedload(ActionLog.expiration_lines),
        )
        .outerjoin(Item, ActionLog.item_id == Item.id)
        .order_by(ordering, ActionLog.id.desc())
        .offset((query.page - 1) * query.page_size)
        .limit(query.page_size)
    )
    return list(session.execute(stmt).unique().scalars().all())
