"""Send grouped inventory alert emails."""

from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.location_filters import alert_matches_location_filter, validate_location_filter_ids
from app.auth.models import Agencies, AgencyEmails
from app.inventory.models import ActionLogs
from app.prediction.formatting import rounded_confidence_percent
from app.shared.clock import utc_now_naive
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

HOURLY_TYPES = {AlertType.STOCKOUT, *ACTION_TYPES}

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


def process_all_alerts(*, force: bool = False) -> dict[str, int]:
    """Send pending alert emails by cadence; leave failed batches pending for retry."""
    stats = {"processed": 0, "sent": 0, "failed": 0}
    now = _now()

    with get_session() as session:
        recipients = _pending_recipients(session)
        if not recipients:
            logger.info("Hourly alert email check finished: no pending recipients")
            return stats

        for recipient in recipients:
            agency = session.get(Agencies, recipient.agency_id)
            if agency is None or not agency.active:
                logger.warning(
                    "Alert email skipped: agency missing or inactive",
                    extra={"agency_id": recipient.agency_id, "agency_email_id": recipient.id},
                )
                continue
            alerts = _alerts_for_recipient(session, recipient, agency, now, force=force)
            type_counts = _alert_type_counts(alerts)
            logger.debug(
                "Alert email recipient evaluated: "
                f"agency_email_id={recipient.id} sendable={len(alerts)} "
                f"force={force} types={_format_counts(type_counts)}",
                extra={
                    "agency_id": agency.id,
                    "agency_email_id": recipient.id,
                    "pending_alerts": len(alerts),
                    "force": force,
                    "type_counts": dict(type_counts),
                },
            )
            if not alerts:
                continue
            stats["processed"] += 1
            if _send_recipient_alerts(session, agency, recipient, alerts, now, force=force):
                _mark_sent(alerts, now)
                session.commit()
                stats["sent"] += 1
                logger.info(
                    "Alert email recipient sent: "
                    f"agency_email_id={recipient.id} sent_alerts={len(alerts)} "
                    f"types={_format_counts(type_counts)}",
                    extra={
                        "agency_id": agency.id,
                        "agency_email_id": recipient.id,
                        "sent_alerts": len(alerts),
                        "type_counts": dict(type_counts),
                    },
                )
            else:
                session.rollback()
                stats["failed"] += 1
                logger.critical(
                    f"Alert email failed after retries: agency_email_id={recipient.id}",
                    extra={"agency_id": agency.id, "agency_email_id": recipient.id},
                )

    logger.info(
        "Hourly alert email check finished: "
        f"recipients_with_email={stats['processed']} sent={stats['sent']} failed={stats['failed']}",
        extra=stats,
    )
    return stats


def _send_recipient_alerts(
    session: Session,
    agency: Agencies,
    recipient: AgencyEmails,
    alerts: list[AlertRecords],
    now: datetime,
    *,
    force: bool,
) -> bool:
    batch = _build_batch(
        session,
        agency,
        recipient,
        alerts,
        include_summaries=force or _is_daily_email_window(agency.timezone, now),
        now=now,
    )
    if batch is None or not batch.sections:
        logger.info(
            "Alert email recipient skipped: no matching sections",
            extra={"agency_id": agency.id, "agency_email_id": recipient.id},
        )
        return True

    return deliver_batch(batch)


def _pending_recipients(session: Session) -> list[AgencyEmails]:
    return list(
        session.execute(
            select(AgencyEmails)
            .join(AlertRecords, AlertRecords.agency_email_id == AgencyEmails.id)
            .where(AlertRecords.action == AlertAction.PENDING)
            .distinct()
            .order_by(AgencyEmails.agency_id, AgencyEmails.id)
        )
        .scalars()
        .all()
    )


def _alerts_for_recipient(
    session: Session,
    recipient: AgencyEmails,
    agency: Agencies,
    now: datetime,
    *,
    force: bool,
) -> list[AlertRecords]:
    alerts = list(
        session.execute(
            select(AlertRecords)
            .where(
                AlertRecords.agency_email_id == recipient.id,
                AlertRecords.action == AlertAction.PENDING,
            )
            .order_by(AlertRecords.created_at, AlertRecords.id)
        )
        .scalars()
        .all()
    )
    alerts = [alert for alert in alerts if _recipient_allows_alert(session, recipient, alert)]
    if force or _is_daily_email_window(agency.timezone, now):
        return alerts
    return [alert for alert in alerts if alert.type in HOURLY_TYPES]


def _build_batch(
    session: Session,
    agency: Agencies,
    recipient: AgencyEmails,
    alerts: list[AlertRecords],
    *,
    include_summaries: bool,
    now: datetime,
) -> EmailBatch | None:
    sections = _build_sections(alerts, agency.timezone)
    if include_summaries:
        sections.extend(_summary_sections(session, agency, recipient, now))
    if not sections:
        return None
    severity = _severity(alerts)
    return EmailBatch(
        agency_email=recipient.email,
        agency_name=agency.display_name,
        generated_at=_display_now(agency.timezone, now),
        subject=_subject(agency.display_name, severity["label"]),
        title=_title(agency.display_name),
        severity_label=severity["label"],
        severity_color=severity["color"],
        summary=_summary(alerts),
        sections=sections,
    )


def _summary(alerts: list[AlertRecords]) -> list[AlertSummaryItem]:
    counts = Counter(alert.type for alert in alerts)
    return [
        AlertSummaryItem(label=LABEL_BY_TYPE[alert_type], count=count)
        for alert_type, count in counts.items()
        if count > 0
    ]


def _build_sections(alerts: list[AlertRecords], timezone: str) -> list[AlertTableSection]:
    sections = [
        section
        for builder in (
            _stockout_section,
            _stockout_pred_section,
            _low_section,
            _low_pred_section,
            _stale_count_section,
            _rare_takeout_section,
        )
        if (section := builder(alerts)) is not None
    ]
    scan_section = _scan_activity_section(alerts, timezone)
    if scan_section is not None:
        sections.append(scan_section)
    return sections


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
    return AlertTableSection(title=title, note=note, columns=columns, rows=rows)


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


def _scan_activity_section(alerts: list[AlertRecords], timezone: str) -> AlertTableSection | None:
    rows = [
        {
            "item_name": alert.details_json.get("item_name"),
            "scan_type": _scan_type(alert.details_json),
            "quantity": alert.details_json.get("quantity"),
            "admin_action": "Yes" if alert.details_json.get("admin_action") else "No",
            "time_scanned": _display_datetime(alert.details_json.get("time_scanned"), timezone),
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


def _summary_sections(
    session: Session,
    agency: Agencies,
    recipient: AgencyEmails,
    now: datetime,
) -> list[AlertTableSection]:
    local_now = _local_now(agency.timezone, now)
    sections: list[AlertTableSection] = []
    for report_type, enabled, bounds in (
        ("Daily", recipient.daily_summary, _prior_day_bounds(local_now)),
        (
            "Weekly",
            recipient.weekly_summary and local_now.weekday() == 0,
            _prior_week_bounds(local_now),
        ),
        (
            "Monthly",
            recipient.monthly_summary and local_now.day == 1,
            _prior_month_bounds(local_now),
        ),
        (
            "Yearly",
            recipient.yearly_summary and local_now.month == 1 and local_now.day == 1,
            _prior_year_bounds(local_now),
        ),
    ):
        if enabled and (section := _summary_section(session, agency.id, report_type, bounds)):
            sections.append(section)
    return sections


def _summary_section(
    session: Session,
    agency_id: int,
    report_type: str,
    bounds: tuple[datetime, datetime],
) -> AlertTableSection | None:
    rows = _summary_rows(session, agency_id, bounds)
    return _simple_section(
        AlertType.COUNT_ACTION,
        f"{report_type} Summary",
        f"{report_type} scan totals for the completed reporting period.",
        rows,
        ["operation_type:Operation", "scan_count:Scans", "quantity_total:Quantity"],
    )


def _summary_rows(
    session: Session,
    agency_id: int,
    bounds: tuple[datetime, datetime],
) -> list[dict[str, Any]]:
    start_at, end_at = bounds
    rows = session.execute(
        select(
            ActionLogs.operation_type,
            func.count(ActionLogs.id),
            func.coalesce(func.sum(ActionLogs.quantity_delta), 0),
        )
        .where(
            ActionLogs.agency_id == agency_id,
            ActionLogs.time_scanned >= start_at,
            ActionLogs.time_scanned < end_at,
        )
        .group_by(ActionLogs.operation_type)
        .order_by(ActionLogs.operation_type)
    ).all()
    return [
        {
            "operation_type": operation.value.title(),
            "scan_count": scan_count,
            "quantity_total": quantity_total,
        }
        for operation, scan_count, quantity_total in rows
    ]


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
    return AlertTableSection(title=title, note=note, columns=columns, rows=rows)


def _subject(agency_name: str, severity_label: str) -> str:
    prefix = {
        "Critical": "🟥 [CRITICAL]",
        "Warning": "🟨 [WARNING]",
        "Activity": "🟩 [ACTIVITY]",
    }[severity_label]
    return f"{prefix} Inventory Alert Report - {agency_name}"


def _title(agency_name: str) -> str:
    return f"Inventory Alert Report - {agency_name}"


def _severity(alerts: list[AlertRecords]) -> dict[str, str]:
    if any(alert.type == AlertType.STOCKOUT for alert in alerts):
        return {"label": "Critical", "color": "#9F1F1F"}
    if any(alert.type in WARNING_TYPES for alert in alerts):
        return {"label": "Warning", "color": "#8A5A00"}
    return {"label": "Activity", "color": "#2F6B4F"}


def _mark_sent(alerts: list[AlertRecords], now: datetime) -> None:
    for alert in alerts:
        alert.action = AlertAction.SENT
        alert.action_at = now


def _recipient_allows_alert(
    session: Session,
    recipient: AgencyEmails,
    alert: AlertRecords,
) -> bool:
    if not bool(getattr(recipient, PREFERENCE_BY_TYPE[alert.type])):
        return False
    try:
        location_ids = validate_location_filter_ids(
            session, recipient.agency_id, recipient.location_filter_ids
        )
    except ValueError as exc:
        logger.warning(
            f"Alert email skipped invalid location filter: agency_email_id={recipient.id}",
            extra={
                "agency_id": recipient.agency_id,
                "agency_email_id": recipient.id,
                "alert_id": alert.id,
                "error": str(exc),
            },
        )
        return False
    return alert_matches_location_filter(location_ids, alert.details_json)


def _display_now(timezone: str, now: datetime) -> str:
    local = convert_utc_to_local(now, timezone) or now
    return _format_local_datetime(local)


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
    value = rounded_confidence_percent(details.get("confidence_percent"))
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


def _alert_type_counts(alerts: list[AlertRecords]) -> Counter[str]:
    return Counter(alert.type.value for alert in alerts)


def _format_counts(counts: Counter[str]) -> str:
    if not counts:
        return "none"
    return ", ".join(f"{key}={counts[key]}" for key in sorted(counts))


def _now() -> datetime:
    return utc_now_naive()


def _is_daily_email_window(timezone: str, now: datetime) -> bool:
    local = _local_now(timezone, now)
    return local.hour == 8


def _local_now(timezone: str, now: datetime) -> datetime:
    aware = now.replace(tzinfo=UTC) if now.tzinfo is None else now
    return aware.astimezone(ZoneInfo(timezone or "UTC"))


def _prior_day_bounds(local_now: datetime) -> tuple[datetime, datetime]:
    end_local = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    return _utc_naive(end_local - timedelta(days=1)), _utc_naive(end_local)


def _prior_week_bounds(local_now: datetime) -> tuple[datetime, datetime]:
    end_local = (local_now - timedelta(days=local_now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return _utc_naive(end_local - timedelta(days=7)), _utc_naive(end_local)


def _prior_month_bounds(local_now: datetime) -> tuple[datetime, datetime]:
    end_local = local_now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    previous_month = (end_local - timedelta(days=1)).replace(day=1)
    return _utc_naive(previous_month), _utc_naive(end_local)


def _prior_year_bounds(local_now: datetime) -> tuple[datetime, datetime]:
    end_local = local_now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    return _utc_naive(end_local.replace(year=end_local.year - 1)), _utc_naive(end_local)


def _utc_naive(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(tzinfo=None)
