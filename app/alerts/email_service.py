"""Send grouped inventory alert emails."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import Agencies, AgencyEmails
from app.shared.clock import utc_now, utc_now_naive
from app.shared.database import get_session
from app.shared.timezone_utils import convert_utc_to_local

from .constants import AlertAction, AlertType
from .email_delivery import deliver_batch
from .models import AlertRecords
from .schema import AlertSummaryItem, AlertTableColumn, AlertTableSection, EmailBatch

WARNING_TYPES = {
    AlertType.STOCKOUT_PRED,
    AlertType.LOW,
    AlertType.LOW_PRED,
    AlertType.STALE_COUNT,
    AlertType.RARE_TAKEOUT,
}

ACTION_TYPES = {
    AlertType.COUNT_ACTION,
    AlertType.RESTOCK_ACTION,
    AlertType.TAKEOUT_ACTION,
    AlertType.TRANSFER_ACTION,
}

PREFERENCE_BY_TYPE = {
    AlertType.STOCKOUT: "alert_for_stockout",
    AlertType.STOCKOUT_PRED: "alert_for_stockout_pred",
    AlertType.LOW: "alert_for_low",
    AlertType.LOW_PRED: "alert_for_low_pred",
    AlertType.STALE_COUNT: "alert_for_stale_count",
    AlertType.RARE_TAKEOUT: "alert_for_rare_takeout",
    AlertType.COUNT_ACTION: "alert_for_count",
    AlertType.RESTOCK_ACTION: "alert_for_restock",
    AlertType.TAKEOUT_ACTION: "alert_for_takeout",
    AlertType.TRANSFER_ACTION: "alert_for_transfer",
}

LABEL_BY_TYPE = {
    AlertType.STOCKOUT: "stockouts",
    AlertType.STOCKOUT_PRED: "predicted stockouts",
    AlertType.LOW: "low stock",
    AlertType.LOW_PRED: "predicted low stock",
    AlertType.STALE_COUNT: "stale counts",
    AlertType.RARE_TAKEOUT: "rare takeouts",
    AlertType.COUNT_ACTION: "count activity",
    AlertType.RESTOCK_ACTION: "restock activity",
    AlertType.TAKEOUT_ACTION: "takeout activity",
    AlertType.TRANSFER_ACTION: "transfer activity",
}


def process_all_alerts() -> dict[str, int]:
    """Send due alert emails; leave failed batches pending for retry."""
    stats = {"processed": 0, "sent": 0}
    now = _now()

    with get_session() as session:
        due = _pending_due_alerts(session, now)
        if not due:
            logger.info("No due alert emails")
            return stats

        for agency_id in sorted({alert.agency_id for alert in due}):
            agency = session.get(Agencies, agency_id)
            if agency is None:
                continue
            alerts = _alerts_for_agency_email(session, agency_id, now)
            if not alerts:
                continue
            stats["processed"] += 1
            if _send_agency_alerts(session, agency, alerts):
                _mark_sent(alerts, now)
                session.commit()
                stats["sent"] += 1
            else:
                session.rollback()

    logger.info("Alert email batch complete", extra=stats)
    return stats


def _send_agency_alerts(
    session: Session,
    agency: Agencies,
    alerts: list[AlertRecords],
) -> bool:
    recipients = list(
        session.execute(
            select(AgencyEmails)
            .where(AgencyEmails.agency_id == agency.id)
            .order_by(AgencyEmails.email)
        )
        .scalars()
        .all()
    )
    if not recipients:
        logger.warning("No alert recipients configured", extra={"agency_id": agency.id})
        return False

    batches: list[EmailBatch] = []
    for recipient in recipients:
        batch = _build_batch(agency, recipient, _filter_alerts_for_recipient(alerts, recipient))
        if batch is not None and batch.sections:
            batches.append(batch)

    if not batches:
        logger.info("No matching alert recipients", extra={"agency_id": agency.id})
        return True

    return all(deliver_batch(batch) for batch in batches)


def _pending_due_alerts(session: Session, now: datetime) -> list[AlertRecords]:
    return list(
        session.execute(
            select(AlertRecords).where(
                AlertRecords.action == AlertAction.PENDING,
                AlertRecords.scheduled <= now,
            )
        )
        .scalars()
        .all()
    )


def _alerts_for_agency_email(session: Session, agency_id: int, now: datetime) -> list[AlertRecords]:
    alerts = list(
        session.execute(
            select(AlertRecords)
            .where(AlertRecords.agency_id == agency_id, AlertRecords.action == AlertAction.PENDING)
            .order_by(AlertRecords.scheduled, AlertRecords.id)
        )
        .scalars()
        .all()
    )
    due_exists = any(alert.scheduled <= now for alert in alerts)
    if not due_exists:
        return []
    return [
        alert
        for alert in alerts
        if alert.scheduled <= now or (alert.type.allow_early and due_exists)
    ]


def _filter_alerts_for_recipient(
    alerts: list[AlertRecords], recipient: AgencyEmails
) -> list[AlertRecords]:
    return [
        alert
        for alert in alerts
        if bool(getattr(recipient, PREFERENCE_BY_TYPE.get(alert.type, ""), False))
    ]


def _build_batch(
    agency: Agencies, recipient: AgencyEmails, alerts: list[AlertRecords]
) -> EmailBatch | None:
    if not alerts:
        return None
    sections = _build_sections(alerts)
    return EmailBatch(
        agency_email=recipient.email,
        agency_name=agency.display_name,
        generated_at=_display_now(agency.timezone),
        subject=_subject(agency.display_name, alerts),
        summary=_summary(alerts),
        sections=sections,
    )


def _summary(alerts: list[AlertRecords]) -> list[AlertSummaryItem]:
    counts = Counter(alert.type for alert in alerts)
    return [
        AlertSummaryItem(label=LABEL_BY_TYPE[alert_type], count=count, color=alert_type.color)
        for alert_type, count in counts.items()
        if count > 0
    ]


def _build_sections(alerts: list[AlertRecords]) -> list[AlertTableSection]:
    return [
        section
        for builder in (
            _stockout_section,
            _stockout_pred_section,
            _low_section,
            _low_pred_section,
            _stale_count_section,
            _rare_takeout_section,
            _scan_activity_section,
        )
        if (section := builder(alerts)) is not None
    ]


def _stockout_section(alerts: list[AlertRecords]) -> AlertTableSection | None:
    return _stock_section(
        alerts,
        AlertType.STOCKOUT,
        "Stockouts",
        "Item is at zero or negative quantity for the listed location(s). Restock immediately.",
        [
            AlertTableColumn(key="item_name", label="Item"),
            AlertTableColumn(key="locations", label="Locations"),
            AlertTableColumn(key="current_total", label="Current Total"),
        ],
    )


def _stockout_pred_section(alerts: list[AlertRecords]) -> AlertTableSection | None:
    return _stock_section(
        alerts,
        AlertType.STOCKOUT_PRED,
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


def _low_section(alerts: list[AlertRecords]) -> AlertTableSection | None:
    return _stock_section(
        alerts,
        AlertType.LOW,
        "Low Stock",
        "Item is below the configured minimum for the listed location(s).",
        [
            AlertTableColumn(key="item_name", label="Item"),
            AlertTableColumn(key="locations", label="Locations"),
            AlertTableColumn(key="current_total", label="Current Total"),
            AlertTableColumn(key="min_quantity", label="Minimum"),
        ],
    )


def _low_pred_section(alerts: list[AlertRecords]) -> AlertTableSection | None:
    return _stock_section(
        alerts,
        AlertType.LOW_PRED,
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
    alerts: list[AlertRecords],
    alert_type: AlertType,
    title: str,
    note: str,
    columns: list[AlertTableColumn],
) -> AlertTableSection | None:
    rows = [_stock_row(alert) for alert in alerts if alert.type == alert_type]
    if not rows:
        return None
    return AlertTableSection(
        title=title, note=note, color=alert_type.color, columns=columns, rows=rows
    )


def _stock_row(alert: AlertRecords) -> dict[str, str | int | float | None]:
    details = alert.details_json
    return {
        "item_name": details.get("item_name"),
        "locations": details.get("location_name"),
        "current_total": _total(details.get("current_total")),
        "min_quantity": details.get("min_quantity"),
        "lead_time_days": _days(details.get("lead_time_days")),
        "prediction": _prediction(details),
        "confidence": _confidence(details),
    }


def _stale_count_section(alerts: list[AlertRecords]) -> AlertTableSection | None:
    rows = [
        {
            "item_name": alert.details_json.get("item_name"),
            "location_name": alert.details_json.get("location_name"),
            "days_since_last_count": alert.details_json.get("days_since_last_count") or "Never",
            "current_total": _total(alert.details_json.get("current_total")),
        }
        for alert in alerts
        if alert.type == AlertType.STALE_COUNT
    ]
    return _simple_section(
        AlertType.STALE_COUNT,
        "Stale Counts",
        "Count these item/location pairs before the next incoming delivery or vendor restock.",
        rows,
        [
            "item_name:Item",
            "location_name:Location",
            "days_since_last_count:Days Since Last Count",
            "current_total:Current Count",
        ],
    )


def _rare_takeout_section(alerts: list[AlertRecords]) -> AlertTableSection | None:
    rows = [
        {
            "item_name": alert.details_json.get("item_name"),
            "location_name": alert.details_json.get("location_name"),
            "days_since_last_takeout": alert.details_json.get("days_since_last_takeout"),
            "current_total": _total(alert.details_json.get("current_total")),
        }
        for alert in alerts
        if alert.type == AlertType.RARE_TAKEOUT
    ]
    return _simple_section(
        AlertType.RARE_TAKEOUT,
        "Rare Takeouts",
        "Takeout activity is unusual for this item/location.",
        rows,
        [
            "item_name:Item",
            "location_name:Location",
            "days_since_last_takeout:Days Since Last Takeout",
            "current_total:Current Count",
        ],
    )


def _scan_activity_section(alerts: list[AlertRecords]) -> AlertTableSection | None:
    rows = [
        {
            "item_name": alert.details_json.get("item_name"),
            "scan_type": _scan_type(alert.details_json),
            "quantity": alert.details_json.get("quantity"),
            "admin_action": "Yes" if alert.details_json.get("admin_action") else "No",
            "time_scanned": alert.details_json.get("time_scanned"),
        }
        for alert in alerts
        if alert.type in ACTION_TYPES
    ]
    return _simple_section(
        AlertType.COUNT_ACTION,
        "Scan Activity",
        "Configured count, restock, takeout, and transfer notifications.",
        rows,
        [
            "item_name:Item",
            "scan_type:Scan Type",
            "quantity:Quantity",
            "admin_action:Admin?",
            "time_scanned:Time Scanned",
        ],
    )


def _simple_section(
    alert_type: AlertType,
    title: str,
    note: str,
    rows: list[dict[str, Any]],
    column_specs: list[str],
) -> AlertTableSection | None:
    if not rows:
        return None
    columns = [
        AlertTableColumn(key=spec.split(":", 1)[0], label=spec.split(":", 1)[1])
        for spec in column_specs
    ]
    return AlertTableSection(
        title=title, note=note, color=alert_type.color, columns=columns, rows=rows
    )


def _subject(agency_name: str, alerts: list[AlertRecords]) -> str:
    emoji = "\U0001f7e2"
    if any(alert.type == AlertType.STOCKOUT for alert in alerts):
        emoji = "\U0001f534"
    elif any(alert.type in WARNING_TYPES for alert in alerts):
        emoji = "\U0001f7e1"
    return f"{emoji} Inventory Alert Report - {agency_name} - {utc_now().date()}"


def _mark_sent(alerts: list[AlertRecords], now: datetime) -> None:
    for alert in alerts:
        alert.action = AlertAction.SENT
        alert.action_at = now


def _display_now(timezone: str) -> str:
    now = utc_now()
    local = convert_utc_to_local(now, timezone) or now
    return local.strftime("%B %d, %Y at %I:%M %p %Z")


def _total(value: Any) -> str:
    return f"{value} total"


def _days(value: Any) -> str:
    return "" if value is None else f"{value} days"


def _prediction(details: dict[str, Any]) -> str | None:
    if days := details.get("days_until_stockout"):
        return f"{days} days until stockout"
    if days := details.get("days_until_low"):
        return f"{days} days until low"
    return None


def _confidence(details: dict[str, Any]) -> str:
    value = details.get("confidence_percent")
    return "" if value is None else f"{value}%"


def _scan_type(details: dict[str, Any]) -> str:
    operation = str(details.get("operation_type", "")).title()
    from_name = details.get("from_location_name")
    to_name = details.get("to_location_name")
    if from_name and to_name:
        return f"{operation} {from_name} -> {to_name}"
    if from_name:
        return f"{operation} from {from_name}"
    if to_name:
        return f"{operation} to {to_name}"
    return operation


def _now() -> datetime:
    return utc_now_naive()
