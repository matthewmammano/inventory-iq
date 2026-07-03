"""Build tabular sections for inventory notification emails."""

from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.models import Agencies, AgencyEmails, AgencyLocations
from app.auth.notification_preferences import due_summary_preferences
from app.inventory.models import ActionLogs, InventoryItemLocationState, Items
from app.prediction.formatting import rounded_confidence_percent
from app.shared.timezone_utils import convert_utc_to_local

from .constants import AlertSeverity, AlertType
from .models import InventoryAlertEvent
from .schema import AlertTableColumn, AlertTableSection

ACTION_TYPES = {
    AlertType.COUNT_ACTION,
    AlertType.RESTOCK_ACTION,
    AlertType.TAKEOUT_ACTION,
    AlertType.TRANSFER_ACTION,
}
RECAP_SECTION_COLOR = AlertSeverity.INFO.color


def build_alert_sections(
    session: Session,
    stock_states: list[InventoryItemLocationState],
    events: list[InventoryAlertEvent],
    timezone: str,
) -> list[AlertTableSection]:
    item_names = _item_names_for_states(session, stock_states)
    location_names = _location_names_for_states(session, stock_states)
    return [
        section
        for section in (
            _stockout_section(stock_states, item_names, location_names, timezone),
            _stockout_forecast_section(stock_states, item_names, location_names),
            _low_stock_section(stock_states, item_names, location_names),
            _low_stock_forecast_section(stock_states, item_names, location_names),
            _event_section(
                events,
                AlertType.STALE_COUNT,
                "Stale Counts",
                "Count these item/location pairs before the next incoming delivery or vendor restock.",
                AlertType.STALE_COUNT.color,
                _stale_count_row,
                lambda event: -int(event.payload_json.get("days_since_last_count") or 0),
                [
                    "item_name:Item",
                    "location_name:Location",
                    "days_since_last_count:Days Since Last Count",
                    "current_total:Current Count",
                ],
            ),
            _event_section(
                events,
                AlertType.RARE_TAKEOUT,
                "Rare Takeouts",
                "Takeout activity is unusual for this item/location.",
                AlertType.RARE_TAKEOUT.color,
                lambda event: _rare_takeout_row(event, timezone),
                lambda event: -int(event.payload_json.get("days_since_last_takeout") or 0),
                [
                    "item_name:Item",
                    "location_name:Location",
                    "days_since_last_takeout:Days Since Last Takeout",
                    "last_takeout_at:Last Takeout At",
                    "current_total:Current Count",
                ],
            ),
            _event_section(
                events,
                ACTION_TYPES,
                "Scan Activity",
                "Configured count, restock, takeout, and transfer notifications.",
                AlertSeverity.INFO.color,
                lambda event: _scan_activity_row(event, timezone),
                lambda event: _sort_datetime_value(event.payload_json.get("time_scanned")) or datetime.min,
                [
                    "item_name:Item",
                    "scan_type:Scan Type",
                    "quantity:Quantity",
                    "admin_action:Admin?",
                    "time_scanned:Time Scanned",
                ],
                reverse=True,
            ),
            _event_section(
                events,
                AlertType.UNKNOWN_UPC,
                "Unknown UPCs",
                "These UPCs need admin review before they can scan to an item.",
                AlertType.UNKNOWN_UPC.color,
                lambda event: _unknown_upc_row(event, timezone),
                lambda event: _sort_datetime_value(event.payload_json.get("created_at")) or datetime.min,
                ["upc:UPC", "lookup_title:Lookup Name", "created_at:First Seen"],
            ),
        )
        if section is not None
    ]


def build_summary_sections(
    session: Session,
    agency: Agencies,
    recipient: AgencyEmails,
    now: datetime,
) -> list[AlertTableSection]:
    local_now = _local_now(agency.timezone, now)
    return [
        section
        for preference in due_summary_preferences(local_now)
        if bool(getattr(recipient, preference.field))
        and preference.bounds is not None
        and (section := _summary_section(session, agency.id, preference.label, preference.bounds(local_now)))
    ]


def _stockout_section(
    states: list[InventoryItemLocationState],
    item_names: dict[int, str],
    location_names: dict[int, str],
    timezone: str,
) -> AlertTableSection | None:
    return _stock_section(
        states,
        item_names,
        location_names,
        AlertType.STOCKOUT,
        "Stockouts",
        "Item is at zero or negative quantity for the listed location(s). Restock immediately.",
        [
            AlertTableColumn(key="item_name", label="Item"),
            AlertTableColumn(key="locations", label="Locations"),
            AlertTableColumn(key="current_total", label="Current Total"),
            AlertTableColumn(key="last_activity_at", label="Last Activity"),
        ],
        timezone=timezone,
    )


def _stockout_forecast_section(
    states: list[InventoryItemLocationState],
    item_names: dict[int, str],
    location_names: dict[int, str],
) -> AlertTableSection | None:
    return _stock_section(
        states,
        item_names,
        location_names,
        AlertType.STOCKOUT_FORECAST,
        "Predicted Stockouts",
        "Forecast shows stockout within the configured lead time.",
        [
            AlertTableColumn(key="item_name", label="Item"),
            AlertTableColumn(key="locations", label="Locations"),
            AlertTableColumn(key="lead_time_days", label="Lead Time"),
            AlertTableColumn(key="prediction", label="Prediction"),
            AlertTableColumn(key="confidence", label="Confidence"),
        ],
    )


def _low_stock_section(
    states: list[InventoryItemLocationState],
    item_names: dict[int, str],
    location_names: dict[int, str],
) -> AlertTableSection | None:
    return _stock_section(
        states,
        item_names,
        location_names,
        AlertType.LOW_STOCK,
        "Low Stock",
        "Item is below the configured minimum for the listed location(s).",
        [
            AlertTableColumn(key="item_name", label="Item"),
            AlertTableColumn(key="locations", label="Locations"),
            AlertTableColumn(key="current_total", label="Current Total"),
            AlertTableColumn(key="min_quantity", label="Minimum"),
        ],
    )


def _low_stock_forecast_section(
    states: list[InventoryItemLocationState],
    item_names: dict[int, str],
    location_names: dict[int, str],
) -> AlertTableSection | None:
    return _stock_section(
        states,
        item_names,
        location_names,
        AlertType.LOW_STOCK_FORECAST,
        "Predicted Low Stock",
        "Forecast shows the item reaching minimum within the configured lead time.",
        [
            AlertTableColumn(key="item_name", label="Item"),
            AlertTableColumn(key="locations", label="Locations"),
            AlertTableColumn(key="lead_time_days", label="Lead Time"),
            AlertTableColumn(key="prediction", label="Prediction"),
            AlertTableColumn(key="confidence", label="Confidence"),
        ],
    )


def _stock_section(
    states: list[InventoryItemLocationState],
    item_names: dict[int, str],
    location_names: dict[int, str],
    alert_type: AlertType,
    title: str,
    note: str,
    columns: list[AlertTableColumn],
    *,
    timezone: str = "UTC",
) -> AlertTableSection | None:
    rows = [
        _stock_row(state, item_names, location_names, timezone)
        for state in sorted(
            (state for state in states if state.effective_alert_type == alert_type),
            key=lambda state: _stock_section_sort_key(state, item_names, alert_type),
        )
    ]
    return _section(title, note, alert_type.color, rows, columns)


def _stock_row(
    state: InventoryItemLocationState,
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
        "prediction": _state_prediction(state),
        "confidence": _format_confidence_percent(state.confidence_percent),
        "last_activity_at": _display_datetime(_iso(state.last_activity_at), timezone),
    }


def _item_names_for_states(session: Session, states: list[InventoryItemLocationState]) -> dict[int, str]:
    item_ids = {state.item_id for state in states}
    if not item_ids:
        return {}
    rows = session.execute(select(Items.id, Items.name).where(Items.id.in_(item_ids))).tuples().all()
    return dict(rows)


def _location_names_for_states(session: Session, states: list[InventoryItemLocationState]) -> dict[int, str]:
    location_ids = {state.agency_location_id for state in states}
    if not location_ids:
        return {}
    rows = session.execute(select(AgencyLocations.id, AgencyLocations.name).where(AgencyLocations.id.in_(location_ids))).tuples().all()
    return dict(rows)


def _event_section(
    events: list[InventoryAlertEvent],
    alert_types: AlertType | set[AlertType],
    title: str,
    note: str,
    color: str,
    row_builder,
    sort_key,
    column_specs: list[str],
    *,
    reverse: bool = False,
) -> AlertTableSection | None:
    allowed_types = alert_types if isinstance(alert_types, set) else {alert_types}
    rows = [row_builder(event) for event in sorted((event for event in events if event.alert_type in allowed_types), key=sort_key, reverse=reverse)]
    return _section(title, note, color, rows, _columns(column_specs))


def _stale_count_row(event: InventoryAlertEvent) -> dict[str, Any]:
    return {
        "item_name": event.payload_json.get("item_name"),
        "location_name": event.payload_json.get("location_name"),
        "days_since_last_count": event.payload_json.get("days_since_last_count", "Never"),
        "current_total": _format_total_quantity(event.payload_json.get("current_total")),
    }


def _rare_takeout_row(event: InventoryAlertEvent, timezone: str) -> dict[str, Any]:
    return {
        "item_name": event.payload_json.get("item_name"),
        "location_name": event.payload_json.get("location_name"),
        "days_since_last_takeout": event.payload_json.get("days_since_last_takeout"),
        "last_takeout_at": _display_datetime(event.payload_json.get("last_takeout_at"), timezone),
        "current_total": _format_total_quantity(event.payload_json.get("current_total")),
    }


def _scan_activity_row(event: InventoryAlertEvent, timezone: str) -> dict[str, Any]:
    return {
        "item_name": event.payload_json.get("item_name"),
        "scan_type": _format_scan_type(event.payload_json),
        "quantity": event.payload_json.get("quantity"),
        "admin_action": "Yes" if event.payload_json.get("admin_action") else "No",
        "time_scanned": _display_datetime(event.payload_json.get("time_scanned"), timezone),
    }


def _unknown_upc_row(event: InventoryAlertEvent, timezone: str) -> dict[str, Any]:
    return {
        "upc": event.payload_json.get("upc"),
        "lookup_title": event.payload_json.get("lookup_title") or "Not found",
        "created_at": _display_datetime(event.payload_json.get("created_at"), timezone),
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
            ActionLogs.operation_type,
            func.count(ActionLogs.id),
            func.coalesce(func.sum(ActionLogs.quantity_delta), 0),
        )
        .where(ActionLogs.agency_id == agency_id, ActionLogs.time_scanned >= start_at, ActionLogs.time_scanned < end_at)
        .group_by(ActionLogs.operation_type)
        .order_by(ActionLogs.operation_type)
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


def _columns(column_specs: list[str]) -> list[AlertTableColumn]:
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


def _format_day_count(value: Any) -> str:
    return "" if value is None else f"{value} days"


def _state_prediction(state: InventoryItemLocationState) -> str | None:
    if state.effective_alert_type == AlertType.STOCKOUT_FORECAST and state.days_until_stockout is not None:
        return f"{state.days_until_stockout} days until stockout"
    if state.effective_alert_type == AlertType.LOW_STOCK_FORECAST and state.days_until_low is not None:
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
