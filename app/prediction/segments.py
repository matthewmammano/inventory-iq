"""Location-level count-to-count training segments."""

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import pairwise

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import AgencyStorages
from app.inventory.constants import OperationType
from app.inventory.models import ActionLogs
from app.prediction.constants import (
    COUNT_CLUSTER_HOURS,
    MODEL_SIGNATURE_VERSION,
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


def get_location_storage_ids(
    session: Session, agency_id: int, agency_location_id: int
) -> list[int]:
    """Return storage IDs inside an agency location."""
    rows = session.execute(
        select(AgencyStorages.id)
        .where(
            AgencyStorages.agency_id == agency_id,
            AgencyStorages.location_id == agency_location_id,
        )
        .order_by(AgencyStorages.name)
    ).all()
    return [row[0] for row in rows]


def build_count_signature(
    session: Session,
    agency_id: int,
    item_id: int,
    agency_location_id: int,
) -> str:
    """Stable signature for count data that affects the trained trend."""
    storage_ids = get_location_storage_ids(session, agency_id, agency_location_id)
    if not storage_ids:
        return hashlib.sha256(MODEL_SIGNATURE_VERSION.encode()).hexdigest()

    rows = session.execute(
        select(
            ActionLogs.id,
            ActionLogs.to_location_id,
            ActionLogs.quantity_delta,
            ActionLogs.time_scanned,
        )
        .where(
            ActionLogs.agency_id == agency_id,
            ActionLogs.item_id == item_id,
            ActionLogs.operation_type == OperationType.COUNT,
            ActionLogs.to_location_id.in_(storage_ids),
        )
        .order_by(ActionLogs.time_scanned, ActionLogs.id)
    ).all()

    digest = hashlib.sha256(MODEL_SIGNATURE_VERSION.encode())
    for log_id, storage_id, quantity, scanned_at in rows:
        digest.update(f"|{log_id}:{storage_id}:{quantity}:{scanned_at}".encode())
    return digest.hexdigest()


def extract_segments(
    session: Session,
    agency_id: int,
    item_id: int,
    agency_location_id: int,
) -> list[TrendSegment]:
    """Build completed location-level trend segments from fresh full-location counts."""
    anchors = _extract_count_anchors(session, agency_id, item_id, agency_location_id)
    return [
        segment
        for start, end in pairwise(anchors)
        if (segment := _build_segment(start, end)) is not None
    ]


def _extract_count_anchors(
    session: Session,
    agency_id: int,
    item_id: int,
    agency_location_id: int,
) -> list[CountAnchor]:
    storage_ids = get_location_storage_ids(session, agency_id, agency_location_id)
    if not storage_ids:
        return []

    count_logs = list(
        session.execute(
            select(ActionLogs)
            .where(
                ActionLogs.agency_id == agency_id,
                ActionLogs.item_id == item_id,
                ActionLogs.operation_type == OperationType.COUNT,
                ActionLogs.to_location_id.in_(storage_ids),
                ActionLogs.time_scanned.isnot(None),
            )
            .order_by(ActionLogs.time_scanned, ActionLogs.id)
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
    count_logs: list[ActionLogs],
    storage_ids: list[int],
    counted_at: datetime,
    window: timedelta,
) -> dict[int, int]:
    start_at = counted_at - window
    latest: dict[int, tuple[datetime, int]] = {}
    for log in count_logs:
        if log.time_scanned is None or log.to_location_id not in storage_ids:
            continue
        if not (start_at <= log.time_scanned <= counted_at):
            continue
        current = latest.get(log.to_location_id)
        if current is None or log.time_scanned >= current[0]:
            latest[log.to_location_id] = (log.time_scanned, log.quantity_delta)
    return {storage_id: quantity for storage_id, (_, quantity) in latest.items()}


def _collapse_count_clusters(anchors: list[CountAnchor], window: timedelta) -> list[CountAnchor]:
    collapsed: list[CountAnchor] = []
    for anchor in anchors:
        if collapsed and anchor.counted_at - collapsed[-1].counted_at < window:
            collapsed[-1] = anchor
            continue
        collapsed.append(anchor)
    return collapsed


def _build_segment(start: CountAnchor, end: CountAnchor) -> TrendSegment | None:
    elapsed_days = (end.counted_at - start.counted_at).total_seconds() / 86_400
    if elapsed_days < 1:
        return None
    trend = (end.total_quantity - start.total_quantity) / elapsed_days
    return TrendSegment(
        start_at=start.counted_at,
        end_at=end.counted_at,
        start_quantity=start.total_quantity,
        end_quantity=end.total_quantity,
        days=elapsed_days,
        trend_per_day=trend,
        weight=_recency_weight(end.counted_at),
    )


def _recency_weight(counted_at: datetime) -> float:
    age_days = (utc_now().date() - counted_at.date()).days
    if age_days <= 30:
        return RECENCY_WEIGHT_30_DAYS
    if age_days <= 90:
        return RECENCY_WEIGHT_90_DAYS
    if age_days <= 365:
        return RECENCY_WEIGHT_365_DAYS
    return RECENCY_WEIGHT_OLD
