"""Generate scheduled inventory alerts.

Cron: 0 7 * * * python tasks/generate_inventory_alerts.py
"""

from loguru import logger

from app import create_app
from app.alerts.alert_service import generate_scheduled_alerts
from app.shared.database import get_session


def run() -> None:
    app = create_app()
    with app.app_context(), get_session() as session:
        count = generate_scheduled_alerts(session)
        session.commit()
        logger.info("Scheduled inventory alerts generated", extra={"rows_checked": count})


if __name__ == "__main__":
    run()
