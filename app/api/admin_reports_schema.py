"""Query and request models for the admin report endpoints."""

from datetime import date

from pydantic import BaseModel, Field

from app.api.schema import LOCKED_INPUT
from app.inventory.count_page_service import ALL_LOCATIONS_ID

FIRST_PAGE = 1


class ReportLocationQuery(BaseModel):
    """Narrow a report to one location; omitted means this device's own location, then the first one."""

    model_config = LOCKED_INPUT

    location_id: int | None = Field(default=None, gt=0)


class HistoryPageQuery(BaseModel):
    """One page of action history; a location_id of 0 spans every location, as the All Locations tab does."""

    model_config = LOCKED_INPUT

    location_id: int | None = Field(default=None, ge=ALL_LOCATIONS_ID)
    page: int = Field(default=FIRST_PAGE, ge=FIRST_PAGE)
    sort: str = ""
    descending: bool = True


class ReportEmailRequest(BaseModel):
    """Which notification recipients one report email goes to, and which location it covers."""

    model_config = LOCKED_INPUT

    notification_recipient_ids: list[int] = Field(min_length=1)
    location_id: int | None = Field(default=None, gt=0)


class HistoryEmailRequest(ReportEmailRequest):
    """A history report email, bounded by agency-local dates; either date may be left out."""

    start_date: date | None = None
    end_date: date | None = None
