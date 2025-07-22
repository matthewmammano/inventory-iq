from pydantic import BaseModel
from typing import List, Dict, Any
from datetime import datetime


class Alert(BaseModel):
    """Single alert for batching"""
    type: str           # "low_stock", "expired_soon", "rare_scan", "zero_stock", "recount_admin"
    item: str           # "Bandages"
    data: Dict[str, Any] = {}  # Values to insert into message template
    urgent: bool = False
    
    @property
    def message(self) -> str:
        """Generate standardized message based on alert type and data"""
        templates = {
            "low_stock": "Running low - only {quantity} left (minimum: {min_quantity})",
            "zero_stock": "OUT OF STOCK - needs immediate restocking", 
            "expired_soon": "Expires in {days} days on {expiry_date}",
            "rare_scan": "Not scanned in {days} days - check if still in stock",
            "recount_admin": "Last recount was {days} days ago - admin review needed"
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
            "low_stock": "⚠️",
            "zero_stock": "🚨", 
            "expired_soon": "📅",
            "rare_scan": "👁️",
            "recount_admin": "📊"
        }
        return icons.get(self.type, "📋")


class EmailBatch(BaseModel):
    """Batched alerts for email delivery"""
    alerts: List[Alert]
    user_email: str
    user_name: str = ""
    
    @property
    def subject(self) -> str:
        urgent_count = sum(1 for a in self.alerts if a.urgent)
        if urgent_count > 0:
            return f"🚨 {urgent_count} URGENT inventory alerts"
        return f"📋 {len(self.alerts)} inventory updates"
    
    def group_by_type(self) -> Dict[str, List[Alert]]:
        """Group alerts by type for organized display"""
        grouped = {}
        for alert in self.alerts:
            if alert.type not in grouped:
                grouped[alert.type] = []
            grouped[alert.type].append(alert)
        return grouped