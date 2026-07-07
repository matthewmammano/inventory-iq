"""Typed JSON payloads stored on alert events."""

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class AlertPayload(BaseModel):
    model_config = ConfigDict(frozen=True)

    def as_json(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class UnknownUpcPayload(AlertPayload):
    unknown_upc_id: int
    upc: str
    lookup_title: str | None
    created_at: datetime


class ScanActivityPayload(AlertPayload):
    action_log_id: int
    item_id: int
    item_name: str
    operation_type: str
    quantity: int
    admin_action: bool
    from_agency_location_id: int | None
    to_agency_location_id: int | None
    from_location_name: str | None
    to_location_name: str | None
    time_scanned: datetime | None


class StaleCountPayload(AlertPayload):
    item_id: int
    item_name: str
    agency_location_id: int
    location_name: str
    days_since_last_count: int | None
    current_total: int
    last_counted_at: datetime | None


class RareTakeoutPayload(AlertPayload):
    item_id: int
    item_name: str
    agency_location_id: int
    location_name: str
    days_since_last_takeout: int | None
    last_takeout_at: datetime
    current_total: int
    rare_scan_days: int


class ExpirationStockPayload(AlertPayload):
    item_id: int
    item_name: str
    storage_id: int
    storage_name: str
    agency_location_id: int
    location_name: str
    expires_on: date
    quantity: int
    days_until_expiration: int
    notice_days: int


class ExpirationCountNeededPayload(AlertPayload):
    item_id: int
    item_name: str
    storage_id: int
    storage_name: str
    agency_location_id: int
    location_name: str
    storage_quantity: int
    tracked_expiration_quantity: int
    difference: int
