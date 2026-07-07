"""Services for retraining inventory trend models."""

from dataclasses import dataclass

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import Agency, Location
from app.inventory.models import Item
from app.prediction.usage_model import train_location_trend


@dataclass(frozen=True, slots=True)
class RetrainingResult:
    agency_count: int
    trend_count: int


def retrain_active_agency_trends(session: Session) -> RetrainingResult:
    agencies = list(session.execute(select(Agency).where(Agency.active.is_(True))).scalars().all())
    logger.debug("Inventory trend retraining agencies loaded", extra={"agency_count": len(agencies)})
    trend_count = 0
    for agency in agencies:
        agency_trends = retrain_agency_trends(session, agency.id)
        logger.debug("Inventory trend retraining agency finished", extra={"agency_id": agency.id, "trend_count": agency_trends})
        trend_count += agency_trends
    return RetrainingResult(agency_count=len(agencies), trend_count=trend_count)


def retrain_agency_trends(session: Session, agency_id: int) -> int:
    items = list(session.execute(select(Item).where(Item.agency_id == agency_id, Item.active.is_(True))).scalars().all())
    locations = list(session.execute(select(Location).where(Location.agency_id == agency_id)).scalars().all())
    trend_count = 0
    for item in items:
        for location in locations:
            trend_count += int(train_location_trend(session, agency_id, item.id, location.id) is not None)
    return trend_count
