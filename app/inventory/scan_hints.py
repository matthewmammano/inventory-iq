"""The two passive hints the scan quantity screen shows: a stale count, or a suggested restock."""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.auth.models import Storage
from app.prediction.bulk_service import BulkService

from .bulk_location_service import required_count_storage_ids
from .constants import OperationType
from .models import Item


@dataclass(frozen=True, slots=True)
class ScanHints:
    stale_count: bool = False
    suggested_restock: int | None = None


def scan_hints(
    session: Session,
    agency_id: int,
    operation_type: OperationType,
    item: Item,
    to_storage: Storage | int | None,
) -> ScanHints:
    """Only COUNT and RESTOCK have a target storage to evaluate against; the rest get nothing."""
    if not isinstance(to_storage, Storage):
        return ScanHints()
    if operation_type.is_count:
        required = required_count_storage_ids(session, agency_id, to_storage.location_id, [item])
        return ScanHints(stale_count=to_storage.id in required.get(item.id, set()))
    if operation_type.is_restock:
        order_amount = BulkService.get_order_amount_for_item(session, agency_id, to_storage.location_id, item)
        return ScanHints(suggested_restock=order_amount or None)
    return ScanHints()
