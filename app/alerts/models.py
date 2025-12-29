"""Pydantic models for alert batching and email delivery."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class Alert(BaseModel):
    """Single alert for batching"""

    type: str  # "low_stock", "expired_soon", "rare_scan", "zero_stock", "count_admin"
    item: str  # "Bandages"
    data: dict[str, Any] = {}  # Values to insert into message template
    urgent: bool = False

    @property
    def message(self) -> str:
        """Generate standardized message based on alert type and data"""
        templates = {
            "low_stock": "Running low - only {quantity} left (minimum: {min_quantity})",
            "zero_stock": "OUT OF STOCK - needs immediate restocking",
            "expired_soon": "Expires in {days} days on {expiry_date}",
            "rare_scan": "Not scanned in {days} days - check if still in stock",
            "count_admin": "Last count was {days} days ago - admin review needed",
        }

        template = templates.get(self.type, "Alert: {item}")
        try:
            return template.format(item=self.item, **self.data)
        except KeyError as e:
            return f"Alert for {self.item} (missing data: {e})"

    @property
    def icon(self) -> str:
        """Get emoji icon for alert type"""
        icons = {
            "low_stock": "WARNING",
            "zero_stock": "ALERT",
            "expired_soon": "EXPIRY",
            "rare_scan": "SCAN",
            "count_admin": "COUNT",
        }
        return icons.get(self.type, "INFO")


class EmailBatch(BaseModel):
    """Batched alerts for email delivery"""

    alerts: list[Alert]
    user_email: str
    user_name: str = ""

    @property
    def subject(self) -> str:
        urgent_count = sum(1 for a in self.alerts if a.urgent)
        if urgent_count > 0:
            return f"ALERT: {urgent_count} URGENT inventory alerts"
        return f"INFO: {len(self.alerts)} inventory updates"

    def group_by_type(self) -> dict[str, list[Alert]]:
        """Group alerts by type for organized display"""
        grouped = {}
        for alert in self.alerts:
            if alert.type not in grouped:
                grouped[alert.type] = []
            grouped[alert.type].append(alert)
        return grouped


# TODO-5: Revisit canonical alert normalization; currently using simple dicts for flexibility.
