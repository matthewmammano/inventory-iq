"""Retrain changed location-level inventory trends.

Production task: python -m tasks.retrain_models
"""

from app import create_app
from app.prediction.retraining_service import retrain_active_agency_trends
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
            result = retrain_active_agency_trends(session)
            session.commit()
            task_result.update({"agency_count": result.agency_count, "trend_count": result.trend_count})


if __name__ == "__main__":
    run()
