"""Retrain changed location-level inventory trends.

Production task: python -m tasks.retrain_models
"""

from app import create_app
from app.prediction.retraining_service import retrain_active_agency_trends
from app.shared.database import get_session
from app.shared.scheduler import SchedulerJobName, run_scheduled_task


def run() -> None:
    """Retrain changed location-level inventory trends for every active agency."""
    app = create_app()
    with app.app_context(), run_scheduled_task("retrain_models", SchedulerJobName.RETRAIN_MODELS) as task_result:
        if task_result is None:
            return
        with get_session() as session:
            result = retrain_active_agency_trends(session)
            session.commit()
            task_result.update({"agency_count": result.agency_count, "trend_count": result.trend_count})


if __name__ == "__main__":
    run()
