"""Location-level count-to-count training segments."""

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import pairwise

from sqlalchemy import or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.auth.models import Storage
from app.inventory.constants import OperationType
from app.inventory.models import ActionLog
from app.prediction.constants import (
    COUNT_CLUSTER_HOURS,
    RECENCY_WEIGHT_30_DAYS,
    RECENCY_WEIGHT_90_DAYS,
    RECENCY_WEIGHT_365_DAYS,
    RECENCY_WEIGHT_OLD,
)
from app.shared.clock import utc_now


@dataclass(frozen=True)
class CountAnchor:
    """A completed full-location count at one point in time."""

    counted_at: datetime
    total_quantity: int


@dataclass(frozen=True)
class TrendSegment:
    """Usage trend between two count anchors."""

    start_at: datetime
    end_at: datetime
    start_quantity: int
    end_quantity: int
    days: float
    trend_per_day: float
    weight: float


@dataclass(frozen=True)
class TrustedMovement:
    """Trusted non-count inventory movement inside a training window."""

    scanned_at: datetime
    operation_type: OperationType
    from_storage_id: int | None
    to_storage_id: int | None
    quantity: int


def get_location_storage_ids(session: Session, agency_id: int, agency_location_id: int) -> list[int]:
    """Return storage IDs inside an agency location."""
    rows = session.execute(
        select(Storage.id)
        .where(
            Storage.agency_id == agency_id,
            Storage.location_id == agency_location_id,
        )
        .order_by(Storage.name)
    ).all()
    return [row[0] for row in rows]


def build_training_signature(
    session: Session,
    agency_id: int,
    item_id: int,
    agency_location_id: int,
) -> str:
    """Stable signature for trusted movement data that affects the trained trend."""
    storage_ids = get_location_storage_ids(session, agency_id, agency_location_id)
    digest = hashlib.sha256()
    digest.update(f"storages:{','.join(str(storage_id) for storage_id in storage_ids)}".encode())
    if not storage_ids:
        return digest.hexdigest()

    rows = session.execute(
        select(
            ActionLog.id,
            ActionLog.operation_type,
            ActionLog.from_storage_id,
            ActionLog.to_storage_id,
            ActionLog.quantity,
            ActionLog.time_scanned,
        )
        .where(
            ActionLog.agency_id == agency_id,
            ActionLog.item_id == item_id,
            _trusted_training_log_filter(storage_ids, include_counts=True),
        )
        .order_by(ActionLog.time_scanned, ActionLog.id)
    ).all()

    for log_id, operation_type, from_storage_id, to_storage_id, quantity, scanned_at in rows:
        digest.update(f"|{log_id}:{operation_type.value}:{from_storage_id}:{to_storage_id}:{quantity}:{scanned_at}".encode())
    return digest.hexdigest()


def extract_segments(
    session: Session,
    agency_id: int,
    item_id: int,
    agency_location_id: int,
) -> list[TrendSegment]:
    """Build completed location-level trend segments from fresh full-location counts."""
    anchors = extract_count_anchors(session, agency_id, item_id, agency_location_id)
    storage_ids = get_location_storage_ids(session, agency_id, agency_location_id)
    trusted_movements = _trusted_movements(session, agency_id, item_id, storage_ids, anchors)
    storage_id_set = set(storage_ids)
    return [segment for start, end in pairwise(anchors) if (segment := _build_segment(trusted_movements, storage_id_set, start, end)) is not None]


def extract_count_anchors(
    session: Session,
    agency_id: int,
    item_id: int,
    agency_location_id: int,
) -> list[CountAnchor]:
    """Return collapsed full-location count anchors used by training and charts."""
    storage_ids = get_location_storage_ids(session, agency_id, agency_location_id)
    if not storage_ids:
        return []

    count_logs = list(
        session.execute(
            select(ActionLog)
            .where(
                ActionLog.agency_id == agency_id,
                ActionLog.item_id == item_id,
                ActionLog.operation_type == OperationType.COUNT,
                ActionLog.to_storage_id.in_(storage_ids),
                ActionLog.time_scanned.isnot(None),
            )
            .order_by(ActionLog.time_scanned, ActionLog.id)
        )
        .scalars()
        .all()
    )
    if not count_logs:
        return []

    anchors: list[CountAnchor] = []
    window = timedelta(hours=COUNT_CLUSTER_HOURS)
    for log in count_logs:
        counted_at = log.time_scanned
        if counted_at is None:
            continue
        latest = _latest_counts_in_window(count_logs, storage_ids, counted_at, window)
        if len(latest) == len(storage_ids):
            anchors.append(CountAnchor(counted_at=counted_at, total_quantity=sum(latest.values())))

    return _collapse_count_clusters(anchors, window)


def _latest_counts_in_window(
    count_logs: list[ActionLog],
    storage_ids: list[int],
    counted_at: datetime,
    window: timedelta,
) -> dict[int, int]:
    start_at = counted_at - window
    latest: dict[int, tuple[datetime, int]] = {}
    for log in count_logs:
        if log.time_scanned is None or log.to_storage_id not in storage_ids:
            continue
        if not (start_at <= log.time_scanned <= counted_at):
            continue
        current = latest.get(log.to_storage_id)
        if current is None or log.time_scanned >= current[0]:
            latest[log.to_storage_id] = (log.time_scanned, log.quantity)
    return {storage_id: quantity for storage_id, (_, quantity) in latest.items()}


def _collapse_count_clusters(anchors: list[CountAnchor], window: timedelta) -> list[CountAnchor]:
    collapsed: list[CountAnchor] = []
    for anchor in anchors:
        if collapsed and anchor.counted_at - collapsed[-1].counted_at < window:
            collapsed[-1] = anchor
            continue
        collapsed.append(anchor)
    return collapsed


def _build_segment(
    trusted_movements: list[TrustedMovement],
    storage_id_set: set[int],
    start: CountAnchor,
    end: CountAnchor,
) -> TrendSegment | None:
    elapsed_days = (end.counted_at - start.counted_at).total_seconds() / 86_400
    if elapsed_days < 1:
        return None
    trusted_delta = _trusted_quantity_delta(trusted_movements, storage_id_set, start.counted_at, end.counted_at)
    inferred_usage = start.total_quantity + trusted_delta - end.total_quantity
    if inferred_usage < 0:
        return None
    trend = -inferred_usage / elapsed_days
    return TrendSegment(
        start_at=start.counted_at,
        end_at=end.counted_at,
        start_quantity=start.total_quantity,
        end_quantity=end.total_quantity,
        days=elapsed_days,
        trend_per_day=trend,
        weight=_recency_weight(end.counted_at),
    )


def _trusted_movements(
    session: Session,
    agency_id: int,
    item_id: int,
    storage_ids: list[int],
    anchors: list[CountAnchor],
) -> list[TrustedMovement]:
    if not storage_ids or len(anchors) < 2:
        return []

    rows = session.execute(
        select(
            ActionLog.time_scanned,
            ActionLog.operation_type,
            ActionLog.from_storage_id,
            ActionLog.to_storage_id,
            ActionLog.quantity,
        )
        .where(
            ActionLog.agency_id == agency_id,
            ActionLog.item_id == item_id,
            ActionLog.time_scanned > anchors[0].counted_at,
            ActionLog.time_scanned <= anchors[-1].counted_at,
            _trusted_training_log_filter(storage_ids, include_counts=False),
        )
        .order_by(ActionLog.time_scanned, ActionLog.id)
    ).all()
    return [
        TrustedMovement(
            scanned_at=scanned_at,
            operation_type=operation_type,
            from_storage_id=from_storage_id,
            to_storage_id=to_storage_id,
            quantity=int(quantity),
        )
        for scanned_at, operation_type, from_storage_id, to_storage_id, quantity in rows
    ]


def _trusted_quantity_delta(
    trusted_movements: list[TrustedMovement],
    storage_id_set: set[int],
    start_at: datetime,
    end_at: datetime,
) -> int:
    delta = 0
    for movement in trusted_movements:
        if not (start_at < movement.scanned_at <= end_at):
            continue
        if movement.operation_type.is_restock and movement.to_storage_id in storage_id_set:
            delta += movement.quantity
            continue
        if movement.operation_type.is_transfer:
            if movement.to_storage_id in storage_id_set:
                delta += movement.quantity
            if movement.from_storage_id in storage_id_set:
                delta -= movement.quantity
    return delta


def _trusted_training_log_filter(storage_ids: list[int], *, include_counts: bool) -> ColumnElement[bool]:
    filters = [
        (ActionLog.operation_type == OperationType.RESTOCK) & ActionLog.to_storage_id.in_(storage_ids),
        (ActionLog.operation_type == OperationType.TRANSFER)
        & (ActionLog.from_storage_id.in_(storage_ids) | ActionLog.to_storage_id.in_(storage_ids)),
    ]
    if include_counts:
        filters.insert(0, (ActionLog.operation_type == OperationType.COUNT) & ActionLog.to_storage_id.in_(storage_ids))
    return or_(*filters)


def _recency_weight(counted_at: datetime) -> float:
    age_days = (utc_now().date() - counted_at.date()).days
    if age_days <= 30:
        return RECENCY_WEIGHT_30_DAYS
    if age_days <= 90:
        return RECENCY_WEIGHT_90_DAYS
    if age_days <= 365:
        return RECENCY_WEIGHT_365_DAYS
    return RECENCY_WEIGHT_OLD
