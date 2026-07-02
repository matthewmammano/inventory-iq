"""CSV export helpers for admin inventory views."""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.auth.models import Agencies, AgencyLocations
from app.inventory.location_operations import build_location_count_rows
from app.inventory.models import ActionLogs, Items
from app.shared.clock import utc_now
from app.shared.email_client import EmailAttachment
from app.shared.timezone_utils import convert_utc_to_local

from .constants import OperationType
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


def build_inventory_count_csv_attachments(session: Session, agency: Agencies) -> list[EmailAttachment]:
    """Return one inventory-count CSV attachment per location."""
    return [_location_count_csv_attachment(session, agency, location) for location in agency.locations]


def build_history_csv_attachment(
    session: Session,
    agency: Agencies,
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
    ]
    rows: list[dict[str, object]] = []
    count_actions = restock_actions = takeout_actions = transfer_actions = admin_actions = 0
    for log in logs:
        count_actions += int(log.operation_type == OperationType.COUNT)
        restock_actions += int(log.operation_type == OperationType.RESTOCK)
        takeout_actions += int(log.operation_type == OperationType.TAKEOUT)
        transfer_actions += int(log.operation_type == OperationType.TRANSFER)
        admin_actions += int(log.admin_action)
        rows.append(
            {
                "Scanned At": _local_timestamp(log, agency.timezone),
                "Item Name": log.item.name if log.item else "",
                "Primary UPC": log.item.upc if log.item else "",
                "Operation": log.operation_type.value.title(),
                "Quantity": log.quantity_delta,
                "From Storage": log.from_location.history_name if log.from_location else "",
                "To Storage": log.to_location.history_name if log.to_location else "",
                "Admin Action": "Yes" if log.admin_action else "No",
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
    )


def _location_count_csv_attachment(session: Session, agency: Agencies, location: AgencyLocations) -> EmailAttachment:
    items, storages, counts = build_location_count_rows(session, agency.id, location.id)
    fieldnames = [
        "Item Name",
        "Primary UPC",
        "Secondary UPCs",
        "Unit",
        "Minimum Level",
        "Total Quantity",
        *[f"{storage.name} Count" for storage in storages],
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
            }
        )
    return _csv_attachment(
        filename=_dated_filename(f"inventory-counts-{location.name}", agency.timezone),
        fieldnames=fieldnames,
        rows=rows,
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


def _secondary_upcs(item: Items) -> str:
    return "; ".join(sorted(upc.upc for upc in item.secondary_upcs if upc.active))


def _history_scope_label(agency: Agencies, agency_location_id: int | None) -> str:
    if agency_location_id is None:
        return "history-all-locations"
    location = next((row for row in agency.locations if row.id == agency_location_id), None)
    return f"history-{location.name}" if location else "history-location"


def _local_timestamp(log: ActionLogs, timezone: str) -> str:
    local = log.get_time_scanned_local(timezone)
    if local is None:
        return ""
    return local.strftime("%Y-%m-%d %H:%M:%S")
