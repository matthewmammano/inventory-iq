"""CSV export helpers for admin inventory views."""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.auth.models import Agency, Location
from app.inventory.expiration_ui_service import ExpirationBreakdown, expiration_breakdowns_by_item
from app.inventory.location_operations import build_location_count_rows
from app.inventory.models import ActionLog, Item
from app.shared.clock import utc_now
from app.shared.email_client import EmailAttachment
from app.shared.timezone_utils import convert_utc_to_local

from .history_service import HISTORY_REPORT_LIMIT, list_history_logs

CSV_BOM = "\ufeff"


@dataclass(frozen=True)
class HistoryExportSummary:
    attachment: EmailAttachment
    total_actions: int
    count_actions: int
    restock_actions: int
    takeout_actions: int
    transfer_actions: int
    admin_actions: int
    email_rows: list[dict[str, str | int | float | None]]


def build_inventory_count_csv_attachments(session: Session, agency: Agency) -> list[EmailAttachment]:
    """Return one inventory-count CSV attachment per location."""
    return [_location_count_csv_attachment(session, agency, location) for location in agency.locations]


def build_history_csv_attachment(
    session: Session,
    agency: Agency,
    agency_location_id: int | None,
    start_utc: datetime | None,
    end_utc: datetime | None,
) -> HistoryExportSummary:
    """Return one history CSV attachment and summary metrics for the selected scope."""
    logs, _ = list_history_logs(session, agency.id, agency_location_id, 1, HISTORY_REPORT_LIMIT, start_utc, end_utc)
    history_fieldnames = [
        "Scanned At",
        "Item Name",
        "Primary UPC",
        "Operation",
        "Quantity",
        "From Storage",
        "To Storage",
        "Admin Action",
        "Expirations",
    ]
    rows: list[dict[str, object]] = []
    email_rows: list[dict[str, str | int | float | None]] = []
    count_actions = restock_actions = takeout_actions = transfer_actions = admin_actions = 0
    for log in logs:
        count_actions += int(log.is_count)
        restock_actions += int(log.is_restock)
        takeout_actions += int(log.is_takeout)
        transfer_actions += int(log.is_transfer)
        admin_actions += int(log.admin_action)
        rows.append(
            {
                "Scanned At": _local_timestamp(log, agency.timezone),
                "Item Name": log.item.name if log.item else "",
                "Primary UPC": log.item.upc if log.item else "",
                "Operation": log.operation_type.value.title(),
                "Quantity": log.quantity,
                "From Storage": log.from_storage.history_name if log.from_storage else "",
                "To Storage": log.to_storage.history_name if log.to_storage else "",
                "Admin Action": "Yes" if log.admin_action else "No",
                "Expirations": log.expiration_summary or "-",
            }
        )
        email_rows.append(
            {
                "time": _local_timestamp(log, agency.timezone),
                "item": log.item.name if log.item else "",
                "type": log.operation_type.value,
                "quantity": log.quantity,
                "from": log.from_storage.history_name if log.from_storage else log.operation_type.value,
                "to": log.to_storage.history_name if log.to_storage else "TAKE",
                "admin": "Yes" if log.admin_action else "No",
                "expirations": log.expiration_summary or "-",
            }
        )
    return HistoryExportSummary(
        attachment=_csv_attachment(
            filename=_dated_filename(_history_scope_label(agency, agency_location_id), agency.timezone),
            fieldnames=list(rows[0].keys()) if rows else history_fieldnames,
            rows=rows,
        ),
        total_actions=len(logs),
        count_actions=count_actions,
        restock_actions=restock_actions,
        takeout_actions=takeout_actions,
        transfer_actions=transfer_actions,
        admin_actions=admin_actions,
        email_rows=email_rows,
    )


def _location_count_csv_attachment(session: Session, agency: Agency, location: Location) -> EmailAttachment:
    items, storages, counts = build_location_count_rows(session, agency.id, location.id, include_secondary_upcs=True)
    expiration_breakdowns = expiration_breakdowns_by_item(session, agency.id, location.id)
    fieldnames = [
        "Item Name",
        "Primary UPC",
        "Secondary UPCs",
        "Unit",
        "Minimum Level",
        "Total Quantity",
        *[f"{storage.name} Count" for storage in storages],
        "Soonest Expiration",
        "Expired",
        "Expiring Soon",
        "Still Good",
    ]
    rows: list[dict[str, object]] = []
    for item in items:
        storage_counts = {f"{storage.name} Count": counts.get((item.id, storage.id), 0) for storage in storages}
        rows.append(
            {
                "Item Name": item.name,
                "Primary UPC": item.upc,
                "Secondary UPCs": _secondary_upcs(item),
                "Unit": item.increments or "Each",
                "Minimum Level": item.min_quantity,
                "Total Quantity": sum(storage_counts.values()),
                **storage_counts,
                **_expiration_export_values(expiration_breakdowns.get(item.id)),
            }
        )
    return _csv_attachment(
        filename=_dated_filename(f"inventory-counts-{location.name}", agency.timezone),
        fieldnames=fieldnames,
        rows=rows,
    )


def build_restock_csv_attachment(agency: Agency, location_name: str, rows: Sequence[Any]) -> EmailAttachment:
    fieldnames = [
        "Item Name",
        "Unit",
        "Total",
        "Total After Lead Time",
        "Usage",
        "Minimum Level",
        "Gap",
        "Maximum Level",
        "Batch Size",
        "Lead Time Days",
        "Soonest Expiration",
        "Expired",
        "Expiring Soon",
        "Still Good",
        "Days Until Stockout",
        "Reorder Date",
        "Last Counted",
        "Confidence",
        "Order Amount",
    ]
    csv_rows = [
        {
            "Item Name": row.item.name,
            "Unit": row.item.increments or "Each",
            "Total": row.current_total,
            "Total After Lead Time": row.projected_lead_time_total if row.projected_lead_time_total is not None else "N/A",
            "Usage": row.usage_display if row.usage_display is not None else "N/A",
            "Minimum Level": row.min_quantity if row.min_quantity > 0 else "",
            "Gap": row.gap_to_min if row.gap_to_min > 0 else "",
            "Maximum Level": row.max_quantity if row.max_quantity > 0 else "",
            "Batch Size": row.item.batch_size or "",
            "Lead Time Days": row.lead_time_days,
            **_expiration_export_values(row.expiration_breakdown),
            "Days Until Stockout": _days_until_stockout_export(row.days_until_stockout),
            "Reorder Date": row.suggested_reorder_date.strftime("%Y-%m-%d") if row.suggested_reorder_date else "N/A",
            "Last Counted": row.last_counted_at.strftime("%Y-%m-%d") if row.last_counted_at else "N/A",
            "Confidence": f"{row.confidence_display}%" if row.confidence_display is not None else "N/A",
            "Order Amount": row.order_amount_display,
        }
        for row in rows
    ]
    return _csv_attachment(
        filename=_dated_filename(f"restock-{location_name}", agency.timezone),
        fieldnames=fieldnames,
        rows=csv_rows,
    )


def _csv_attachment(filename: str, fieldnames: list[str], rows: list[dict[str, object]]) -> EmailAttachment:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return EmailAttachment(
        filename=filename,
        content_bytes=(CSV_BOM + buffer.getvalue()).encode("utf-8"),
    )


def _dated_filename(label: str, timezone: str, *, suffix: str = ".csv") -> str:
    local_now = convert_utc_to_local(utc_now(), timezone) or utc_now()
    stamp = local_now.strftime("%Y-%m-%d")
    slug = _slugify(label)
    return f"{slug}-{stamp}{suffix}"


def _slugify(value: str) -> str:
    return re.sub(r"-{2,}", "-", re.sub(r"[^a-z0-9]+", "-", value.lower())).strip("-") or "export"


def _secondary_upcs(item: Item) -> str:
    return "; ".join(sorted(upc.upc for upc in item.secondary_upcs if upc.active))


def _expiration_export_values(expiration: ExpirationBreakdown | None) -> dict[str, object]:
    if expiration is None:
        return {
            "Soonest Expiration": "-",
            "Expired": "-",
            "Expiring Soon": "-",
            "Still Good": "-",
        }
    return {
        "Soonest Expiration": expiration.soonest_label,
        "Expired": expiration.expired_count,
        "Expiring Soon": expiration.expiring_soon_count,
        "Still Good": expiration.good_count,
    }


def _days_until_stockout_export(days_until_stockout: int | None) -> int | str:
    if days_until_stockout is None:
        return "N/A"
    return min(days_until_stockout, 365)


def _history_scope_label(agency: Agency, agency_location_id: int | None) -> str:
    if agency_location_id is None:
        return "history-all-locations"
    location = next((row for row in agency.locations if row.id == agency_location_id), None)
    return f"history-{location.name}" if location else "history-location"


def _local_timestamp(log: ActionLog, timezone: str) -> str:
    local = log.get_time_scanned_local(timezone)
    if local is None:
        return ""
    return local.strftime("%Y-%m-%d %H:%M:%S")
