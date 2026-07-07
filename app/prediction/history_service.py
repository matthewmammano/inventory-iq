"""Item/location trend chart data."""

from datetime import datetime

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
    operation_points = _operation_points(session, agency_id, item.id, storage_ids)
    trend = get_inventory_trend(session, agency_id, item.id, location.id)
    visible_trend = _visible_trend(trend.trend_per_day) if trend and trend.trend_per_day is not None else None
    return ItemTrendChartResponse(
        item_id=item.id,
        item_name=item.name,
        agency_location_id=location.id,
        location_name=location.name,
        count_points=[_point(anchor.counted_at, anchor.total_quantity, OperationType.COUNT.value) for anchor in count_anchors],
        operation_points=operation_points,
        trendline_points=_trendline_points(
            count_anchors[-1] if count_anchors else None,
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


def _trendline_points(
    last_count: CountAnchor | None,
    trend_per_day: float | None,
) -> list[TrendChartPoint]:
    if last_count is None or trend_per_day is None:
        return []
    now = _now_for(last_count.counted_at)
    return [
        _point(last_count.counted_at, last_count.total_quantity, "TREND"),
        _trend_point(now, last_count.counted_at, last_count.total_quantity, trend_per_day),
    ]


def _trend_point(at: datetime, start_at: datetime, start_quantity: int, trend_per_day: float) -> TrendChartPoint:
    days = (at - start_at).total_seconds() / 86_400
    return _point(at, max(start_quantity + trend_per_day * days, 0.0), "TREND")


def _now_for(value: datetime) -> datetime:
    return utc_now().replace(tzinfo=value.tzinfo) if value.tzinfo else utc_now().replace(tzinfo=None)


def _visible_trend(trend_per_day: float) -> float:
    return round(trend_per_day, 2) or 0.0


def _point(at: datetime, quantity: float, operation: str | None) -> TrendChartPoint:
    return TrendChartPoint(at=at.isoformat(), quantity=round(float(quantity), 2), operation=operation)
