"""Retrain changed location-level inventory trends.

Production task: python -m tasks.retrain_models
"""

from loguru import logger
from sqlalchemy import select

from app import create_app
from app.auth.models import Agencies, AgencyLocations
from app.inventory.models import Items
from app.prediction.usage_model import train_location_trend
from app.shared.database import get_session
from app.shared.scheduler import SchedulerJobName, claimed_scheduler_run, scheduler_daily_period_key
from app.shared.task_logging import logged_task


def run() -> None:
    """Retrain changed location-level inventory trends for every active agency."""
    app = create_app()
    with app.app_context(), get_session() as session, logged_task("retrain_models") as task_result:
        period_key = scheduler_daily_period_key()
        with claimed_scheduler_run(SchedulerJobName.RETRAIN_MODELS, period_key) as run_id:
            if run_id is None:
                task_result["skipped"] = "already_claimed"
                return
            task_result["period_key"] = period_key
            agencies = list(session.execute(select(Agencies).where(Agencies.active.is_(True))).scalars().all())
            logger.debug("Inventory trend retraining agencies loaded", extra={"agency_count": len(agencies)})
            total = 0
            for agency in agencies:
                retrained = _retrain_agency(session, agency.id)
                logger.debug("Inventory trend retraining agency finished", extra={"agency_id": agency.id, "trend_count": retrained})
                total += retrained
            session.commit()
            task_result.update({"agency_count": len(agencies), "trend_count": total})


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
