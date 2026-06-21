"""Retrain changed location-level inventory trends.

Cron: 0 2 * * * python -m tasks.retrain_models
"""

from loguru import logger
from sqlalchemy import select

from app import create_app
from app.auth.models import Agencies, AgencyLocations
from app.inventory.models import Items
from app.prediction.usage_model import train_location_trend
from app.shared.database import get_session


def run() -> None:
    """Retrain changed location-level inventory trends for every active agency."""
    app = create_app()
    with app.app_context(), get_session() as session:
        agencies = list(session.execute(select(Agencies).where(Agencies.active.is_(True))).scalars().all())
        total = 0
        for agency in agencies:
            total += _retrain_agency(session, agency.id)
        session.commit()
    logger.info("Inventory trend retraining task finished", extra={"trend_count": total})


def _retrain_agency(session, agency_id: int) -> int:
    items = list(session.execute(select(Items).where(Items.agency_id == agency_id, Items.active.is_(True))).scalars().all())
    locations = list(session.execute(select(AgencyLocations).where(AgencyLocations.agency_id == agency_id)).scalars().all())

    count = 0
    for item in items:
        for location in locations:
            if train_location_trend(session, agency_id, item.id, location.id):
                count += 1
    return count


if __name__ == "__main__":
    run()
