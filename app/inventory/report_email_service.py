"""Email reports for admin inventory views."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alerts.constants import AlertSeverity
from app.alerts.email_delivery import deliver_batch
from app.alerts.schema import AlertSummaryItem, AlertTableColumn, AlertTableSection, EmailBatch
from app.auth.models import Agency, Location, NotificationRecipient
from app.inventory.expiration_ui_service import ExpirationBreakdown, expiration_breakdowns_by_item
from app.inventory.export_service import (
    HistoryExportSummary,
    build_history_csv_attachment,
    build_inventory_count_csv_attachments,
    build_restock_csv_attachment,
)
from app.inventory.location_operations import build_location_count_rows
from app.inventory.restock_page_service import RestockPageRow, build_restock_page_rows
from app.shared.clock import utc_now
from app.shared.email_client import EmailAttachment
from app.shared.email_subjects import HISTORY_LOGS_TITLE, INVENTORY_COUNTS_TITLE, RESTOCK_REPORT_TITLE, report_subject
from app.shared.timezone_utils import convert_utc_to_local

REPORT_SEVERITY = AlertSeverity.INFO
ReportRow = dict[str, str | int | float | None]


@dataclass(frozen=True, slots=True)
class InventoryCountReportRow:
    item_name: str
    minimum: int
    total: int
    storage_counts: dict[int, int]
    soonest_expiration: str
    expired: int | str
    expiring_soon: int | str
    still_good: int | str

    def as_email_row(self) -> ReportRow:
        row: ReportRow = {
            "item": self.item_name,
            "minimum": self.minimum,
            "total": self.total,
            "soonest_expiration": self.soonest_expiration,
            "expired": self.expired,
            "expiring_soon": self.expiring_soon,
            "still_good": self.still_good,
        }
        for storage_id, count in self.storage_counts.items():
            row[f"storage_{storage_id}"] = count
        return row


def send_inventory_count_report(
    session: Session,
    agency_id: int,
    notification_recipient_ids: list[int],
) -> tuple[int, int]:
    agency, recipients = _agency_recipients(session, agency_id, notification_recipient_ids)
    if agency is None or not recipients:
        return 0, 0
    return _deliver_batch_to_recipients(
        _build_inventory_count_batch(session, agency),
        recipients,
        tuple(build_inventory_count_csv_attachments(session, agency)),
    )


def send_history_report(
    session: Session,
    agency_id: int,
    notification_recipient_ids: list[int],
    agency_location_id: int | None,
    start_utc: datetime | None,
    end_utc: datetime | None,
    start_date: str,
    end_date: str,
) -> tuple[int, int]:
    agency, recipients = _agency_recipients(session, agency_id, notification_recipient_ids)
    if agency is None or not recipients:
        return 0, 0
    export = build_history_csv_attachment(session, agency, agency_location_id, start_utc, end_utc)
    return _deliver_batch_to_recipients(
        _build_history_batch(agency, export, start_date, end_date),
        recipients,
        (export.attachment,),
    )


def send_restock_report(
    session: Session,
    agency_id: int,
    notification_recipient_ids: list[int],
    agency_location_id: int | None,
) -> tuple[int, int]:
    agency, recipients = _agency_recipients(session, agency_id, notification_recipient_ids)
    if agency is None or not recipients:
        return 0, 0
    location = _report_location(agency, agency_location_id)
    if location is None:
        return 0, 0
    rows = build_restock_page_rows(session, agency.id, location.id)
    return _deliver_batch_to_recipients(
        _build_restock_batch(agency, location.name, rows),
        recipients,
        (build_restock_csv_attachment(agency, location.name, rows),),
    )


def _agency_recipients(
    session: Session,
    agency_id: int,
    notification_recipient_ids: list[int],
) -> tuple[Agency | None, list[NotificationRecipient]]:
    agency = session.get(Agency, agency_id)
    if agency is None:
        return None, []
    recipients = _selected_recipients(session, agency.id, notification_recipient_ids)
    return agency, recipients


def _deliver_batch_to_recipients(
    batch_base: EmailBatch,
    recipients: list[NotificationRecipient],
    attachments: tuple[EmailAttachment, ...],
) -> tuple[int, int]:
    sent = 0
    for recipient in recipients:
        batch = batch_base.model_copy(update={"agency_email": recipient.email})
        sent += int(deliver_batch(batch, attachments=attachments))
    return sent, len(recipients)


def _selected_recipients(
    session: Session,
    agency_id: int,
    notification_recipient_ids: list[int],
) -> list[NotificationRecipient]:
    if not notification_recipient_ids:
        return []
    return list(
        session.execute(
            select(NotificationRecipient)
            .where(
                NotificationRecipient.agency_id == agency_id,
                NotificationRecipient.id.in_(notification_recipient_ids),
                NotificationRecipient.active.is_(True),
            )
            .order_by(NotificationRecipient.email)
        )
        .scalars()
        .all()
    )


def _build_inventory_count_batch(session: Session, agency: Agency) -> EmailBatch:
    sections, rows, stockouts, below_min = _inventory_sections(session, agency)
    return _report_batch(
        agency,
        INVENTORY_COUNTS_TITLE,
        "This email includes the current inventory report. A separate CSV is attached for each location.",
        summary=[
            AlertSummaryItem(label="Locations", count=len(sections), color=REPORT_SEVERITY.color),
            AlertSummaryItem(label="Item", count=rows, color=REPORT_SEVERITY.color),
            AlertSummaryItem(label="Out Of Stock", count=stockouts, color=REPORT_SEVERITY.color),
            AlertSummaryItem(label="Below Minimum", count=below_min, color=REPORT_SEVERITY.color),
        ],
        sections=sections,
    )


def _build_history_batch(
    agency: Agency,
    export: HistoryExportSummary,
    start_date: str,
    end_date: str,
) -> EmailBatch:
    return _report_batch(
        agency,
        HISTORY_LOGS_TITLE,
        (f"This email includes a filtered history summary. The CSV attachment covers {start_date or 'the beginning'} through {end_date or 'today'}."),
        summary=[
            AlertSummaryItem(label="Actions", count=export.total_actions, color=REPORT_SEVERITY.color),
            AlertSummaryItem(label="Counts", count=export.count_actions, color=REPORT_SEVERITY.color),
            AlertSummaryItem(label="Restocks", count=export.restock_actions, color=REPORT_SEVERITY.color),
            AlertSummaryItem(label="Takeouts", count=export.takeout_actions, color=REPORT_SEVERITY.color),
            AlertSummaryItem(label="Transfers", count=export.transfer_actions, color=REPORT_SEVERITY.color),
            AlertSummaryItem(label="Admin Actions", count=export.admin_actions, color=REPORT_SEVERITY.color),
        ],
        sections=[
            AlertTableSection(
                title="History",
                note="Filtered inventory activity.",
                color=REPORT_SEVERITY.color,
                columns=[
                    AlertTableColumn(key="time", label="Time"),
                    AlertTableColumn(key="item", label="Item"),
                    AlertTableColumn(key="type", label="Type"),
                    AlertTableColumn(key="quantity", label="Qty"),
                    AlertTableColumn(key="from", label="From"),
                    AlertTableColumn(key="to", label="To"),
                    AlertTableColumn(key="admin", label="Admin?"),
                    AlertTableColumn(key="expirations", label="Expirations"),
                ],
                rows=export.email_rows,
            )
        ]
        if export.email_rows
        else [],
    )


def _build_restock_batch(agency: Agency, location_name: str, rows: list[RestockPageRow]) -> EmailBatch:
    order_needed = sum(1 for row in rows if row.order_amount and row.order_amount > 0)
    return _report_batch(
        agency,
        RESTOCK_REPORT_TITLE,
        f"This email includes restock recommendations for {location_name}. Review current stock before ordering.",
        summary=[
            AlertSummaryItem(label="Item", count=len(rows), color=REPORT_SEVERITY.color),
            AlertSummaryItem(label="Order Needed", count=order_needed, color=REPORT_SEVERITY.color),
        ],
        sections=[
            AlertTableSection(
                title=location_name,
                note="Estimated reorder needs by item.",
                color=REPORT_SEVERITY.color,
                columns=[
                    AlertTableColumn(key="item", label="Item"),
                    AlertTableColumn(key="unit", label="Unit"),
                    AlertTableColumn(key="total", label="Total"),
                    AlertTableColumn(key="projected_total", label="Total After Lead Time"),
                    AlertTableColumn(key="usage", label="Usage"),
                    AlertTableColumn(key="minimum", label="Min"),
                    AlertTableColumn(key="gap", label="Gap"),
                    AlertTableColumn(key="maximum", label="Max"),
                    AlertTableColumn(key="batch_size", label="Batch Size"),
                    AlertTableColumn(key="lead_time_days", label="Lead Time Days"),
                    AlertTableColumn(key="soonest_expiration", label="Soonest Expiration"),
                    AlertTableColumn(key="expired", label="Expired"),
                    AlertTableColumn(key="expiring_soon", label="Expiring Soon"),
                    AlertTableColumn(key="still_good", label="Still Good"),
                    AlertTableColumn(key="days_until_stockout", label="Days Until Stockout"),
                    AlertTableColumn(key="reorder_date", label="Reorder Date"),
                    AlertTableColumn(key="last_counted", label="Last Counted"),
                    AlertTableColumn(key="confidence", label="Confidence"),
                    AlertTableColumn(key="order_amount", label="Order Amount"),
                ],
                rows=[_restock_email_row(row) for row in rows],
            )
        ]
        if rows
        else [],
    )


def _report_batch(
    agency: Agency,
    title: str,
    intro: str,
    *,
    summary: list[AlertSummaryItem],
    sections: list[AlertTableSection],
) -> EmailBatch:
    return EmailBatch(
        agency_email="report@example.com",
        agency_name=agency.display_name,
        generated_at=_display_now(agency.timezone),
        subject=report_subject(title, agency.display_name),
        title=title,
        intro=intro,
        severity_label=REPORT_SEVERITY.value,
        severity_color=REPORT_SEVERITY.color,
        summary=summary,
        sections=sections,
    )


def _inventory_sections(
    session: Session,
    agency: Agency,
) -> tuple[list[AlertTableSection], int, int, int]:
    sections = []
    row_count = 0
    stockouts = 0
    below_min = 0
    for location in agency.locations:
        items, storages, counts = build_location_count_rows(session, agency.id, location.id)
        expiration_breakdowns = expiration_breakdowns_by_item(session, agency.id, location.id)
        rows: list[ReportRow] = []
        for item in items:
            storage_counts = {storage.id: counts.get((item.id, storage.id), 0) for storage in storages}
            total = sum(storage_counts.values())
            expiration = expiration_breakdowns.get(item.id)
            row_count += 1
            stockouts += int(total <= 0)
            below_min += int(0 < total <= item.min_quantity)
            rows.append(
                InventoryCountReportRow(
                    item.name,
                    item.min_quantity,
                    total,
                    storage_counts,
                    *_expiration_email_values(expiration),
                ).as_email_row()
            )
        if rows:
            sections.append(
                AlertTableSection(
                    title=location.name,
                    note="Current inventory counts by storage.",
                    color=REPORT_SEVERITY.color,
                    columns=[
                        AlertTableColumn(key="item", label="Item"),
                        *[AlertTableColumn(key=f"storage_{storage.id}", label=storage.name) for storage in storages],
                        AlertTableColumn(key="minimum", label="Min"),
                        AlertTableColumn(key="total", label="Total"),
                        AlertTableColumn(key="soonest_expiration", label="Soonest Expiration"),
                        AlertTableColumn(key="expired", label="Expired"),
                        AlertTableColumn(key="expiring_soon", label="Expiring Soon"),
                        AlertTableColumn(key="still_good", label="Still Good"),
                    ],
                    rows=rows,
                )
            )
    return sections, row_count, stockouts, below_min


def _report_location(agency: Agency, agency_location_id: int | None) -> Location | None:
    if not agency.locations:
        return None
    if agency_location_id is None:
        return agency.locations[0]
    return next((location for location in agency.locations if location.id == agency_location_id), agency.locations[0])


def _restock_email_row(row: RestockPageRow) -> ReportRow:
    soonest_expiration, expired, expiring_soon, still_good = _expiration_email_values(row.expiration_breakdown)
    return {
        "item": row.item.name,
        "unit": row.item.increments,
        "total": row.current_total,
        "projected_total": row.projected_lead_time_total if row.projected_lead_time_total is not None else "N/A",
        "usage": row.usage_display if row.usage_display is not None else "N/A",
        "minimum": row.min_quantity if row.min_quantity > 0 else "-",
        "gap": row.gap_to_min if row.gap_to_min > 0 else "",
        "maximum": row.max_quantity if row.max_quantity > 0 else "-",
        "batch_size": row.item.batch_size if row.item.batch_size else "-",
        "lead_time_days": row.lead_time_days,
        "soonest_expiration": soonest_expiration,
        "expired": expired,
        "expiring_soon": expiring_soon,
        "still_good": still_good,
        "days_until_stockout": _days_until_stockout_display(row.days_until_stockout),
        "reorder_date": row.suggested_reorder_date.strftime("%Y-%m-%d") if row.suggested_reorder_date else "N/A",
        "last_counted": row.last_counted_at.strftime("%Y-%m-%d") if row.last_counted_at else "N/A",
        "confidence": f"{row.confidence_display}%" if row.confidence_display is not None else "N/A",
        "order_amount": row.order_amount_display,
    }


def _expiration_email_values(expiration: ExpirationBreakdown | None) -> tuple[str, int | str, int | str, int | str]:
    if expiration is None:
        return "-", "-", "-", "-"
    return (
        expiration.soonest_label,
        expiration.expired_count,
        expiration.expiring_soon_count,
        expiration.good_count,
    )


def _days_until_stockout_display(days_until_stockout: int | None) -> int | str:
    if days_until_stockout is None:
        return "N/A"
    return min(days_until_stockout, 365)


def _display_now(timezone: str) -> str:
    local = convert_utc_to_local(utc_now(), timezone) or datetime.now()
    return local.strftime("%B %d, %Y %H:%M")
