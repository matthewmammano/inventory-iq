"""Pydantic email composition models for alerts."""

from pydantic import BaseModel, EmailStr, Field


class AlertSummaryItem(BaseModel):
    label: str
    count: int
    color: str


class AlertTableColumn(BaseModel):
    key: str
    label: str


class AlertTableSection(BaseModel):
    title: str
    note: str
    color: str
    columns: list[AlertTableColumn]
    rows: list[dict[str, str | int | float | None]]


class EmailBatch(BaseModel):
    agency_email: EmailStr
    agency_name: str
    generated_at: str
    subject: str
    summary: list[AlertSummaryItem] = Field(default_factory=list)
    sections: list[AlertTableSection] = Field(default_factory=list)
