"""Run the full inventory alert safety audit.

Production task: python -m tasks.generate_inventory_alerts
"""

from loguru import logger

from app import create_app
from app.alerts.alert_service import generate_scheduled_alerts
from app.shared.database import get_session


def run() -> None:
    """Generate safety-audit alert rows for all active agencies."""
    app = create_app()
    with app.app_context(), get_session() as session:
        count = generate_scheduled_alerts(session)
        session.commit()
        logger.info("Inventory safety audit generated alerts", extra={"rows_checked": count})


if __name__ == "__main__":
    run()
