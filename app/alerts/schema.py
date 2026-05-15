"""Pydantic email composition models for alerts."""

from pydantic import BaseModel, EmailStr, Field


class AlertSummaryItem(BaseModel):
    """One summary card in an alert email."""

    label: str
    count: int


class AlertTableColumn(BaseModel):
    """Display metadata for one alert table column."""

    key: str
    label: str


class AlertTableSection(BaseModel):
    """One rendered alert table section."""

    title: str
    note: str
    columns: list[AlertTableColumn]
    rows: list[dict[str, str | int | float | None]]


class EmailBatch(BaseModel):
    """Fully composed alert email for one recipient."""

    agency_email: EmailStr
    agency_name: str
    generated_at: str
    subject: str
    severity_label: str
    severity_color: str
    summary: list[AlertSummaryItem] = Field(default_factory=list)
    sections: list[AlertTableSection] = Field(default_factory=list)
