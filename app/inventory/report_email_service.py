"""Email reports for admin inventory views."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alerts.email_delivery import deliver_batch
from app.alerts.schema import AlertSummaryItem, AlertTableColumn, AlertTableSection, EmailBatch
from app.auth.models import Agencies, AgencyEmails
from app.inventory.location_operations import build_location_count_rows
from app.shared.clock import utc_now
from app.shared.timezone_utils import convert_utc_to_local

REPORT_COLOR = "#2F6B4F"
ReportRow = dict[str, str | int | float | None]


def send_inventory_count_report(
    session: Session,
    agency_id: int,
    agency_email_ids: list[int],
) -> tuple[int, int]:
    agency = session.get(Agencies, agency_id)
    if agency is None:
        return 0, 0
    recipients = _selected_recipients(session, agency.id, agency_email_ids)
    if not recipients:
        return 0, 0

    batch_base = _build_report_batch(session, agency)
    sent = 0
    for recipient in recipients:
        batch = batch_base.model_copy(update={"agency_email": recipient.email})
        sent += int(deliver_batch(batch))
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
            select(AgencyEmails).where(AgencyEmails.agency_id == agency_id, AgencyEmails.id.in_(agency_email_ids)).order_by(AgencyEmails.email)
        )
        .scalars()
        .all()
    )


def _build_report_batch(session: Session, agency: Agencies) -> EmailBatch:
    sections, rows, stockouts, below_min = _inventory_sections(session, agency)
    return EmailBatch(
        agency_email="report@example.com",
        agency_name=agency.display_name,
        generated_at=_display_now(agency.timezone),
        subject=f"Inventory Levels Report - {agency.display_name}",
        title=f"Inventory Levels Report - {agency.display_name}",
        severity_label="Report",
        severity_color=REPORT_COLOR,
        summary=[
            AlertSummaryItem(label="locations", count=len(sections)),
            AlertSummaryItem(label="inventory rows", count=rows),
            AlertSummaryItem(label="stockouts", count=stockouts),
            AlertSummaryItem(label="below minimum", count=below_min),
        ],
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
