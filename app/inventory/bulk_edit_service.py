"""Business service for bulk inventory edits."""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from .bulk_location_service import save_bulk_location_count, save_bulk_location_restock
from .expiration_service import ExpirationAllocation, sync_expiration_alerts_after_save


class BulkEditEmptyError(ValueError):
    """Raised when a bulk edit contains no count or restock entries."""


@dataclass(frozen=True, slots=True)
class BulkEditSaveResult:
    count_entry_count: int
    restock_entry_count: int

    @property
    def total_entry_count(self) -> int:
        return self.count_entry_count + self.restock_entry_count


def save_bulk_edit(
    session: Session,
    *,
    agency_id: int,
    agency_location_id: int,
    counts: dict[tuple[int, int], int],
    restocks: dict[tuple[int, int], int],
    expiration_allocations_by_key: dict[str, list[ExpirationAllocation]] | None = None,
) -> BulkEditSaveResult:
    if not counts and not any(quantity > 0 for quantity in restocks.values()):
        raise BulkEditEmptyError("No count or restock entries entered.")

    count_logs = save_bulk_location_count(session, agency_id, agency_location_id, counts, expiration_allocations_by_key or {}) if counts else 0
    restock_logs = (
        save_bulk_location_restock(session, agency_id, agency_location_id, restocks, expiration_allocations_by_key or {}) if restocks else 0
    )
    sync_expiration_alerts_after_save(session, agency_id, any((expiration_allocations_by_key or {}).values()))
    session.commit()
    return BulkEditSaveResult(count_logs, restock_logs)
