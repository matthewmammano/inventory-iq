"""Build tabular sections for inventory notification emails."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.models import Agency, Location, NotificationRecipient
from app.auth.notification_preferences import due_summary_preferences
from app.inventory.models import ActionLog, InventoryItemLocationState, Item
from app.prediction.formatting import rounded_confidence_percent
from app.shared.timezone_utils import convert_utc_to_local

from .constants import AlertSeverity, AlertType
from .models import Alert
from .schema import AlertTableColumn, AlertTableSection

StockRow = tuple[AlertType, InventoryItemLocationState]

ACTION_TYPES = {
    AlertType.COUNT_ACTION,
    AlertType.RESTOCK_ACTION,
    AlertType.TAKEOUT_ACTION,
    AlertType.TRANSFER_ACTION,
}
RECAP_SECTION_COLOR = AlertSeverity.INFO.color


@dataclass(frozen=True, slots=True)
class StockSectionSpec:
    alert_type: AlertType
    title: str
    note: str
    column_specs: tuple[str, ...]
    use_timezone: bool = False


@dataclass(frozen=True, slots=True)
class EventSectionSpec:
    alert_types: AlertType | set[AlertType]
    title: str
    note: str
    color: str
    row_builder: Callable[[Alert, str], dict[str, Any]]
    sort_key: Callable[[Alert], Any]
    column_specs: tuple[str, ...]
    reverse: bool = False


STOCK_SECTION_SPECS = (
    StockSectionSpec(
        AlertType.STOCKOUT,
        "Stockouts",
        "Item is at zero or negative quantity for the listed location(s). Restock immediately.",
        ("item_name:Item", "locations:Locations", "current_total:Current Total", "last_activity_at:Last Activity"),
        use_timezone=True,
    ),
    StockSectionSpec(
        AlertType.STOCKOUT_FORECAST,
        "Predicted Stockouts",
        "Forecast shows stockout within the configured lead time.",
        ("item_name:Item", "locations:Locations", "lead_time_days:Lead Time", "prediction:Prediction", "confidence:Confidence"),
    ),
    StockSectionSpec(
        AlertType.LOW_STOCK,
        "Low Stock",
        "Item is below the configured minimum for the listed location(s).",
        ("item_name:Item", "locations:Locations", "current_total:Current Total", "min_quantity:Minimum"),
    ),
    StockSectionSpec(
        AlertType.LOW_STOCK_FORECAST,
        "Predicted Low Stock",
        "Forecast shows the item reaching minimum within the configured lead time.",
        ("item_name:Item", "locations:Locations", "lead_time_days:Lead Time", "prediction:Prediction", "confidence:Confidence"),
    ),
)

EVENT_SECTION_SPECS = (
    EventSectionSpec(
        AlertType.STALE_COUNT,
        "Stale Counts",
        "Count these item/location pairs before the next incoming delivery or vendor restock.",
        AlertType.STALE_COUNT.color,
        lambda event, _timezone: _stale_count_row(event),
        lambda event: -int(event.detail.get("days_since_last_count") or 0),
        ("item_name:Item", "location_name:Location", "days_since_last_count:Days Since Last Count", "current_total:Current Count"),
    ),
    EventSectionSpec(
        AlertType.RARE_TAKEOUT,
        "Rare Takeouts",
        "Takeout activity is unusual for this item/location.",
        AlertType.RARE_TAKEOUT.color,
        lambda event, timezone: _rare_takeout_row(event, timezone),
        lambda event: -int(event.detail.get("days_since_last_takeout") or 0),
        (
            "item_name:Item",
            "location_name:Location",
            "days_since_last_takeout:Days Since Last Takeout",
            "last_takeout_at:Last Takeout At",
            "current_total:Current Count",
        ),
    ),
    EventSectionSpec(
        ACTION_TYPES,
        "Scan Activity",
        "Configured count, restock, takeout, and transfer notifications.",
        AlertSeverity.INFO.color,
        lambda event, timezone: _scan_activity_row(event, timezone),
        lambda event: _sort_datetime_value(event.detail.get("time_scanned")) or datetime.min,
        ("item_name:Item", "scan_type:Scan Type", "quantity:Quantity", "admin_action:Admin?", "time_scanned:Time Scanned"),
        reverse=True,
    ),
    EventSectionSpec(
        AlertType.UNKNOWN_UPC,
        "Unknown UPCs",
        "These UPCs need admin review before they can scan to an item.",
        AlertType.UNKNOWN_UPC.color,
        lambda event, timezone: _unknown_upc_row(event, timezone),
        lambda event: _sort_datetime_value(event.detail.get("created_at")) or datetime.min,
        ("upc:UPC", "lookup_title:Lookup Name", "created_at:First Seen"),
    ),
    EventSectionSpec(
        AlertType.EXPIRED_STOCK,
        "Expired Stock",
        "These tracked expiration dates have passed. Remove or replace this stock now.",
        AlertType.EXPIRED_STOCK.color,
        lambda event, _timezone: _expiration_stock_row(event),
        lambda event: (event.detail.get("expires_on") or "", event.detail.get("item_name") or ""),
        ("item_name:Item", "location_name:Location", "storage_name:Storage", "quantity:Quantity", "expires_on:Expired On", "status:Status"),
    ),
    EventSectionSpec(
        AlertType.EXPIRING_SOON,
        "Expiring Soon",
        "These tracked quantities expire within the configured warning window. Use oldest stock first or replace it.",
        AlertType.EXPIRING_SOON.color,
        lambda event, _timezone: _expiration_stock_row(event),
        lambda event: (int(event.detail.get("days_until_expiration") or 0), event.detail.get("item_name") or ""),
        ("item_name:Item", "location_name:Location", "storage_name:Storage", "quantity:Quantity", "expires_on:Expires On", "status:Status"),
    ),
    EventSectionSpec(
        AlertType.EXPIRATION_COUNT_NEEDED,
        "Expiration Counts Needed",
        "Some stock is counted, but its expiration dates are missing or incomplete. "
        "Check the items in this storage and enter the correct expiration dates.",
        AlertType.EXPIRATION_COUNT_NEEDED.color,
        lambda event, _timezone: _expiration_count_needed_row(event),
        lambda event: (abs(int(event.detail.get("difference") or 0)), event.detail.get("item_name") or ""),
        (
            "item_name:Item",
            "location_name:Location",
            "storage_name:Storage",
            "storage_quantity:Storage Count",
            "tracked_expiration_quantity:Expiration Count",
            "difference:Difference",
        ),
        reverse=True,
    ),
)


def build_alert_sections(
    session: Session,
    stock_rows: list[StockRow],
    discrete_alerts: list[Alert],
    timezone: str,
) -> list[AlertTableSection]:
    states = [state for _, state in stock_rows]
    item_names = _item_names_for_states(session, states)
    location_names = _location_names_for_states(session, states)
    return [
        section
        for section in (
            *[
                _stock_section(stock_rows, item_names, location_names, spec, timezone=timezone if spec.use_timezone else "UTC")
                for spec in STOCK_SECTION_SPECS
            ],
            *[_event_section(discrete_alerts, spec, timezone) for spec in EVENT_SECTION_SPECS],
        )
        if section is not None
    ]


def build_summary_sections(
    session: Session,
    agency: Agency,
    recipient: NotificationRecipient,
    now: datetime,
) -> list[AlertTableSection]:
    local_now = _local_now(agency.timezone, now)
    return [
        section
        for preference in due_summary_preferences(local_now)
        if recipient.preference_enabled(preference.key)
        and preference.bounds is not None
        and (section := _summary_section(session, agency.id, preference.label, preference.bounds(local_now)))
    ]


def _stock_section(
    stock_rows: list[StockRow],
    item_names: dict[int, str],
    location_names: dict[int, str],
    spec: StockSectionSpec,
    *,
    timezone: str = "UTC",
) -> AlertTableSection | None:
    rows = [
        _stock_row(state, spec.alert_type, item_names, location_names, timezone)
        for _, state in sorted(
            ((alert_type, state) for alert_type, state in stock_rows if alert_type == spec.alert_type),
            key=lambda pair: _stock_section_sort_key(pair[1], item_names, spec.alert_type),
        )
    ]
    return _section(spec.title, spec.note, spec.alert_type.color, rows, _columns(spec.column_specs))


def _stock_row(
    state: InventoryItemLocationState,
    alert_type: AlertType,
    item_names: dict[int, str],
    location_names: dict[int, str],
    timezone: str,
) -> dict[str, str | int | float | None]:
    return {
        "item_name": item_names.get(state.item_id, str(state.item_id)),
        "locations": location_names.get(state.agency_location_id, str(state.agency_location_id)),
        "current_total": _format_total_quantity(state.total_quantity),
        "min_quantity": state.min_quantity_snapshot,
        "lead_time_days": _format_day_count(state.lead_time_days_snapshot),
        "prediction": _state_prediction(state, alert_type),
        "confidence": _format_confidence_percent(state.confidence_percent),
        "last_activity_at": _display_datetime(_iso(state.last_activity_at), timezone),
    }


def _item_names_for_states(session: Session, states: list[InventoryItemLocationState]) -> dict[int, str]:
    item_ids = {state.item_id for state in states}
    if not item_ids:
        return {}
    rows = session.execute(select(Item.id, Item.name).where(Item.id.in_(item_ids))).tuples().all()
    return dict(rows)


def _location_names_for_states(session: Session, states: list[InventoryItemLocationState]) -> dict[int, str]:
    location_ids = {state.agency_location_id for state in states}
    if not location_ids:
        return {}
    rows = session.execute(select(Location.id, Location.name).where(Location.id.in_(location_ids))).tuples().all()
    return dict(rows)


def _event_section(
    discrete_alerts: list[Alert],
    spec: EventSectionSpec,
    timezone: str,
) -> AlertTableSection | None:
    allowed_types = spec.alert_types if isinstance(spec.alert_types, set) else {spec.alert_types}
    rows = [
        spec.row_builder(alert, timezone)
        for alert in sorted((alert for alert in discrete_alerts if alert.alert_type in allowed_types), key=spec.sort_key, reverse=spec.reverse)
    ]
    return _section(spec.title, spec.note, spec.color, rows, _columns(spec.column_specs))


def _stale_count_row(event: Alert) -> dict[str, Any]:
    return {
        "item_name": event.detail.get("item_name"),
        "location_name": event.detail.get("location_name"),
        "days_since_last_count": event.detail.get("days_since_last_count", "Never"),
        "current_total": _format_total_quantity(event.detail.get("current_total")),
    }


def _rare_takeout_row(event: Alert, timezone: str) -> dict[str, Any]:
    return {
        "item_name": event.detail.get("item_name"),
        "location_name": event.detail.get("location_name"),
        "days_since_last_takeout": event.detail.get("days_since_last_takeout"),
        "last_takeout_at": _display_datetime(event.detail.get("last_takeout_at"), timezone),
        "current_total": _format_total_quantity(event.detail.get("current_total")),
    }


def _scan_activity_row(event: Alert, timezone: str) -> dict[str, Any]:
    return {
        "item_name": event.detail.get("item_name"),
        "scan_type": _format_scan_type(event.detail),
        "quantity": event.detail.get("quantity"),
        "admin_action": "Yes" if event.detail.get("admin_action") else "No",
        "time_scanned": _display_datetime(event.detail.get("time_scanned"), timezone),
    }


def _unknown_upc_row(event: Alert, timezone: str) -> dict[str, Any]:
    return {
        "upc": event.detail.get("upc"),
        "lookup_title": event.detail.get("lookup_title") or "Not found",
        "created_at": _display_datetime(event.detail.get("created_at"), timezone),
    }


def _expiration_stock_row(event: Alert) -> dict[str, Any]:
    days_until = int(event.detail.get("days_until_expiration") or 0)
    return {
        "item_name": event.detail.get("item_name"),
        "location_name": event.detail.get("location_name"),
        "storage_name": event.detail.get("storage_name"),
        "quantity": _format_total_quantity(event.detail.get("quantity")),
        "expires_on": _display_date(event.detail.get("expires_on")),
        "status": _expiration_status(days_until),
    }


def _expiration_count_needed_row(event: Alert) -> dict[str, Any]:
    return {
        "item_name": event.detail.get("item_name"),
        "location_name": event.detail.get("location_name"),
        "storage_name": event.detail.get("storage_name"),
        "storage_quantity": _format_total_quantity(event.detail.get("storage_quantity")),
        "tracked_expiration_quantity": _format_total_quantity(event.detail.get("tracked_expiration_quantity")),
        "difference": _format_signed_quantity(event.detail.get("difference")),
    }


def _summary_section(
    session: Session,
    agency_id: int,
    report_type: str,
    bounds: tuple[datetime, datetime],
) -> AlertTableSection | None:
    start_at, end_at = bounds
    rows = session.execute(
        select(
            ActionLog.operation_type,
            func.count(ActionLog.id),
            func.coalesce(func.sum(ActionLog.quantity), 0),
        )
        .where(ActionLog.agency_id == agency_id, ActionLog.time_scanned >= start_at, ActionLog.time_scanned < end_at)
        .group_by(ActionLog.operation_type)
        .order_by(ActionLog.operation_type)
    ).all()
    return _section(
        f"{report_type} Summary",
        f"{report_type} scan totals for the completed reporting period.",
        RECAP_SECTION_COLOR,
        [
            {
                "operation_type": operation.value.title(),
                "scan_count": scan_count,
                "quantity_total": quantity_total,
            }
            for operation, scan_count, quantity_total in rows
        ],
        _columns(["operation_type:Operation", "scan_count:Scans", "quantity_total:Quantity"]),
    )


def _section(
    title: str,
    note: str,
    color: str,
    rows: list[dict[str, Any]],
    columns: list[AlertTableColumn],
) -> AlertTableSection | None:
    if not rows:
        return None
    return AlertTableSection(title=title, note=note, color=color, columns=columns, rows=rows)


def _columns(column_specs: Sequence[str]) -> list[AlertTableColumn]:
    return [AlertTableColumn(key=spec.split(":", 1)[0], label=spec.split(":", 1)[1]) for spec in column_specs]


def _stock_section_sort_key(
    state: InventoryItemLocationState,
    item_names: dict[int, str],
    alert_type: AlertType,
) -> tuple[Any, ...]:
    item_name = item_names.get(state.item_id, str(state.item_id)).lower()
    if alert_type == AlertType.STOCKOUT:
        return (item_name, state.agency_location_id)
    if alert_type == AlertType.STOCKOUT_FORECAST:
        return (state.days_until_stockout is None, state.days_until_stockout or 0.0, item_name, state.agency_location_id)
    if alert_type == AlertType.LOW_STOCK:
        return (state.total_quantity, item_name, state.agency_location_id)
    return (state.days_until_low is None, state.days_until_low or 0.0, item_name, state.agency_location_id)


def _sort_datetime_value(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _display_datetime(value: Any, timezone: str) -> str:
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return str(value).replace("T", " ").split(".", maxsplit=1)[0]
    local = convert_utc_to_local(parsed, timezone) or parsed
    return _format_local_datetime(local)


def _format_local_datetime(value: datetime) -> str:
    return value.strftime("%B %d, %Y %H:%M")


def _format_total_quantity(value: Any) -> str:
    return f"{value} total"


def _format_signed_quantity(value: Any) -> str:
    quantity = int(value or 0)
    prefix = "+" if quantity > 0 else ""
    return f"{prefix}{quantity}"


def _format_day_count(value: Any) -> str:
    return "" if value is None else f"{value} days"


def _display_date(value: Any) -> str:
    if not value:
        return ""
    try:
        return datetime.fromisoformat(str(value)).strftime("%B %d, %Y")
    except ValueError:
        return str(value)


def _expiration_status(days_until: int) -> str:
    if days_until < 0:
        days_past = abs(days_until)
        return f"{days_past} day{'s' if days_past != 1 else ''} expired"
    if days_until == 0:
        return "Expires today"
    return f"{days_until} day{'s' if days_until != 1 else ''} left"


def _state_prediction(state: InventoryItemLocationState, alert_type: AlertType) -> str | None:
    if alert_type == AlertType.STOCKOUT_FORECAST and state.days_until_stockout is not None:
        return f"{state.days_until_stockout} days until stockout"
    if alert_type == AlertType.LOW_STOCK_FORECAST and state.days_until_low is not None:
        return f"{state.days_until_low} days until low"
    return None


def _format_confidence_percent(value: Any) -> str:
    rounded = rounded_confidence_percent(value)
    return f"{rounded}%" if rounded is not None else ""


def _format_scan_type(payload: dict[str, Any]) -> str:
    operation = str(payload.get("operation_type", "")).title()
    from_name = payload.get("from_location_name")
    to_name = payload.get("to_location_name")
    if from_name and to_name:
        return f"{operation} {from_name} -> {to_name}"
    if from_name:
        return f"{operation} from {from_name}"
    if to_name:
        return f"{operation} to {to_name}"
    return operation


def _local_now(timezone: str, now: datetime) -> datetime:
    aware = now.replace(tzinfo=UTC) if now.tzinfo is None else now
    return aware.astimezone(ZoneInfo(timezone or "UTC"))


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None
