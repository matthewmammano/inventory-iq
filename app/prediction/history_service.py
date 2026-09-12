"""Item/location trend chart data."""

from datetime import datetime
from itertools import pairwise

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.auth.models import Location
from app.inventory.constants import OperationType
from app.inventory.models import ActionLog, Item
from app.prediction.formatting import format_usage_rate
from app.prediction.schema import ItemTrendChartResponse, TrendChartPoint
from app.prediction.segments import CountAnchor, extract_count_anchors, get_location_storage_ids
from app.prediction.usage_model import get_inventory_trend
from app.shared.clock import utc_now


def build_item_trend_chart(
    session: Session,
    agency_id: int,
    item: Item,
    location: Location,
) -> ItemTrendChartResponse:
    """Return count anchors, operation dots, and learned trendline for one location."""
    storage_ids = get_location_storage_ids(session, agency_id, location.id)
    count_anchors = extract_count_anchors(session, agency_id, item.id, location.id)
    discrepancies = _count_discrepancies(session, agency_id, item.id, storage_ids, count_anchors)
    operation_points = _operation_points(session, agency_id, item.id, storage_ids)
    trend = get_inventory_trend(session, agency_id, item.id, location.id)
    visible_trend = _visible_trend(trend.trend_per_day) if trend and trend.trend_per_day is not None else None
    return ItemTrendChartResponse(
        item_id=item.id,
        item_name=item.name,
        agency_location_id=location.id,
        location_name=location.name,
        count_points=[
            _point(anchor.counted_at, anchor.total_quantity, OperationType.COUNT.value, *discrepancies.get(anchor.counted_at, (None, None)))
            for anchor in count_anchors
        ],
        operation_points=operation_points,
        trendline_points=_trendline_points(
            _last_known_point(count_anchors, operation_points),
            visible_trend,
        ),
        trend_per_day=visible_trend,
        trend_rate_display=format_usage_rate(visible_trend),
        confidence_percent=trend.confidence_percent if trend else None,
    )


def _operation_points(
    session: Session,
    agency_id: int,
    item_id: int,
    storage_ids: list[int],
) -> list[TrendChartPoint]:
    if not storage_ids:
        return []
    rows = session.execute(
        select(ActionLog)
        .where(
            ActionLog.agency_id == agency_id,
            ActionLog.item_id == item_id,
            or_(
                ActionLog.from_storage_id.in_(storage_ids),
                ActionLog.to_storage_id.in_(storage_ids),
            ),
            ActionLog.time_scanned.isnot(None),
        )
        .order_by(ActionLog.time_scanned, ActionLog.id)
    ).scalars()
    quantities: dict[int, int] = dict.fromkeys(storage_ids, 0)
    operation_points: list[TrendChartPoint] = []
    for log in rows:
        scanned_at = log.time_scanned
        if scanned_at is None:
            continue
        before = sum(quantities.values())
        _apply_log(quantities, log)
        total = sum(quantities.values())
        if log.is_count:
            continue
        if total != before:
            operation_points.append(_point(scanned_at, total, log.operation_type.value))
    return operation_points


def _count_discrepancies(
    session: Session,
    agency_id: int,
    item_id: int,
    storage_ids: list[int],
    anchors: list[CountAnchor],
) -> dict[datetime, tuple[float, float]]:
    """Map each count anchor (after the first) to (expected_quantity, discrepancy).

    "Expected" replays only trusted restock/takeout/transfer activity since the prior
    count onto that prior count's total. A nonzero discrepancy means the physical
    count disagreed with what logged activity predicted.
    """
    if not storage_ids or len(anchors) < 2:
        return {}
    rows = list(
        session.execute(
            select(ActionLog)
            .where(
                ActionLog.agency_id == agency_id,
                ActionLog.item_id == item_id,
                ActionLog.operation_type != OperationType.COUNT,
                ActionLog.time_scanned.isnot(None),
                or_(
                    ActionLog.from_storage_id.in_(storage_ids),
                    ActionLog.to_storage_id.in_(storage_ids),
                ),
                ActionLog.time_scanned >= anchors[0].counted_at,
                ActionLog.time_scanned < anchors[-1].counted_at,
            )
            .order_by(ActionLog.time_scanned, ActionLog.id)
        ).scalars()
    )
    discrepancies: dict[datetime, tuple[float, float]] = {}
    for prev_anchor, anchor in pairwise(anchors):
        quantities: dict[int, int] = dict.fromkeys(storage_ids, 0)
        for log in rows:
            scanned_at = log.time_scanned
            if scanned_at is not None and prev_anchor.counted_at <= scanned_at < anchor.counted_at:
                _apply_log(quantities, log)
        expected = prev_anchor.total_quantity + sum(quantities.values())
        discrepancies[anchor.counted_at] = (expected, anchor.total_quantity - expected)
    return discrepancies


def _apply_log(quantities: dict[int, int], log: ActionLog) -> None:
    to_storage_id = log.to_storage_id
    from_storage_id = log.from_storage_id
    if log.is_count and to_storage_id is not None and to_storage_id in quantities:
        quantities[to_storage_id] = log.quantity
        return
    if to_storage_id is not None and to_storage_id in quantities:
        quantities[to_storage_id] += log.quantity
    if from_storage_id is not None and from_storage_id in quantities:
        quantities[from_storage_id] -= log.quantity


def _last_known_point(
    count_anchors: list[CountAnchor],
    operation_points: list[TrendChartPoint],
) -> tuple[datetime, float] | None:
    """Most recent real datapoint: a count or a logged restock/takeout/transfer, whichever is newer."""
    candidates: list[tuple[datetime, float]] = []
    if count_anchors:
        candidates.append((count_anchors[-1].counted_at, count_anchors[-1].total_quantity))
    if operation_points:
        candidates.append((datetime.fromisoformat(operation_points[-1].at), operation_points[-1].quantity))
    return max(candidates, key=lambda point: point[0]) if candidates else None


def _trendline_points(
    last_point: tuple[datetime, float] | None,
    trend_per_day: float | None,
) -> list[TrendChartPoint]:
    if last_point is None or trend_per_day is None:
        return []
    last_at, last_quantity = last_point
    now = _now_for(last_at)
    return [
        _point(last_at, last_quantity, "TREND"),
        _trend_point(now, last_at, last_quantity, trend_per_day),
    ]


def _trend_point(at: datetime, start_at: datetime, start_quantity: float, trend_per_day: float) -> TrendChartPoint:
    days = (at - start_at).total_seconds() / 86_400
    return _point(at, max(start_quantity + trend_per_day * days, 0.0), "TREND")


def _now_for(value: datetime) -> datetime:
    return utc_now().replace(tzinfo=value.tzinfo) if value.tzinfo else utc_now().replace(tzinfo=None)


def _visible_trend(trend_per_day: float) -> float:
    return round(trend_per_day, 2) or 0.0


def _point(
    at: datetime,
    quantity: float,
    operation: str | None,
    expected_quantity: float | None = None,
    discrepancy: float | None = None,
) -> TrendChartPoint:
    return TrendChartPoint(
        at=at.isoformat(),
        quantity=round(float(quantity), 2),
        operation=operation,
        expected_quantity=round(float(expected_quantity), 2) if expected_quantity is not None else None,
        discrepancy=round(float(discrepancy), 2) if discrepancy is not None else None,
    )
