"""Email reports for admin inventory views."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alerts.constants import AlertSeverity
from app.alerts.email_delivery import deliver_batch
from app.alerts.schema import AlertSummaryItem, AlertTableColumn, AlertTableSection, EmailBatch
from app.auth.models import Agencies, AgencyEmails
from app.inventory.export_service import (
    HistoryExportSummary,
    build_history_csv_attachment,
    build_inventory_count_csv_attachments,
)
from app.inventory.location_operations import build_location_count_rows
from app.shared.clock import utc_now
from app.shared.email_client import EmailAttachment
from app.shared.email_subjects import HISTORY_LOGS_TITLE, INVENTORY_COUNTS_TITLE, report_subject
from app.shared.timezone_utils import convert_utc_to_local

REPORT_SEVERITY = AlertSeverity.INFO
ReportRow = dict[str, str | int | float | None]


def send_inventory_count_report(
    session: Session,
    agency_id: int,
    agency_email_ids: list[int],
) -> tuple[int, int]:
    agency, recipients = _agency_recipients(session, agency_id, agency_email_ids)
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
    agency_email_ids: list[int],
    agency_location_id: int | None,
    start_utc: datetime | None,
    end_utc: datetime | None,
    start_date: str,
    end_date: str,
) -> tuple[int, int]:
    agency, recipients = _agency_recipients(session, agency_id, agency_email_ids)
    if agency is None or not recipients:
        return 0, 0
    export = build_history_csv_attachment(session, agency, agency_location_id, start_utc, end_utc)
    return _deliver_batch_to_recipients(
        _build_history_batch(agency, export, start_date, end_date),
        recipients,
        (export.attachment,),
    )


def _agency_recipients(
    session: Session,
    agency_id: int,
    agency_email_ids: list[int],
) -> tuple[Agencies | None, list[AgencyEmails]]:
    agency = session.get(Agencies, agency_id)
    if agency is None:
        return None, []
    recipients = _selected_recipients(session, agency.id, agency_email_ids)
    return agency, recipients


def _deliver_batch_to_recipients(
    batch_base: EmailBatch,
    recipients: list[AgencyEmails],
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
    agency_email_ids: list[int],
) -> list[AgencyEmails]:
    if not agency_email_ids:
        return []
    return list(
        session.execute(
            select(AgencyEmails)
            .where(
                AgencyEmails.agency_id == agency_id,
                AgencyEmails.id.in_(agency_email_ids),
                AgencyEmails.active.is_(True),
            )
            .order_by(AgencyEmails.email)
        )
        .scalars()
        .all()
    )


def _build_inventory_count_batch(session: Session, agency: Agencies) -> EmailBatch:
    sections, rows, stockouts, below_min = _inventory_sections(session, agency)
    return _report_batch(
        agency,
        INVENTORY_COUNTS_TITLE,
        "This email includes the current inventory report. A separate CSV is attached for each location.",
        summary=[
            AlertSummaryItem(label="Locations", count=len(sections), color=REPORT_SEVERITY.color),
            AlertSummaryItem(label="Items", count=rows, color=REPORT_SEVERITY.color),
            AlertSummaryItem(label="Out Of Stock", count=stockouts, color=REPORT_SEVERITY.color),
            AlertSummaryItem(label="Below Minimum", count=below_min, color=REPORT_SEVERITY.color),
        ],
        sections=sections,
    )


def _build_history_batch(
    agency: Agencies,
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
        sections=[],
    )


def _report_batch(
    agency: Agencies,
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
    agency: Agencies,
) -> tuple[list[AlertTableSection], int, int, int]:
    sections = []
    row_count = 0
    stockouts = 0
    below_min = 0
    for location in agency.locations:
        items, storages, counts = build_location_count_rows(session, agency.id, location.id)
        rows: list[ReportRow] = []
        for item in items:
            total = sum(counts.get((item.id, storage.id), 0) for storage in storages)
            row_count += 1
            stockouts += int(total <= 0)
            below_min += int(0 < total <= item.min_quantity)
            row: ReportRow = {
                "item": item.name,
                "minimum": item.min_quantity,
                "total": total,
            }
            row.update({f"storage_{storage.id}": counts.get((item.id, storage.id), 0) for storage in storages})
            rows.append(row)
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
                    ],
                    rows=rows,
                )
            )
    return sections, row_count, stockouts, below_min


def _display_now(timezone: str) -> str:
    local = convert_utc_to_local(utc_now(), timezone) or datetime.now()
    return local.strftime("%B %d, %Y %H:%M")
