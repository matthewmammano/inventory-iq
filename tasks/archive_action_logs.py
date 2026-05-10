"""Archive action logs older than 1 year to JSON.
Cron: 0 4 1 * * python tasks/archive_action_logs.py
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from loguru import logger
from sqlalchemy import delete, select

from app import create_app
from app.inventory.models import ActionLogs
from app.shared.database import get_session


def archive_action_logs() -> None:
    app = create_app()
    with app.app_context():
        cutoff = datetime.now(UTC) - timedelta(days=365)

        with get_session() as s:
            old_logs = list(
                s.execute(select(ActionLogs).where(ActionLogs.time_scanned < cutoff))
                .scalars()
                .all()
            )

        if not old_logs:
            logger.info("No logs to archive")
            return

        archive_dir = Path(app.instance_path) / "archives"
        archive_dir.mkdir(exist_ok=True)
        archive_file = archive_dir / f"action_logs_{datetime.now().strftime('%Y%m%d')}.json"

        with archive_file.open("w") as f:
            json.dump(
                {
                    "archived_date": datetime.now().isoformat(),
                    "logs": [
                        {
                            "id": log.id,
                            "agency_id": log.agency_id,
                            "item_id": log.item_id,
                            "operation_type": log.operation_type.value
                            if log.operation_type
                            else None,
                            "quantity_delta": log.quantity_delta,
                            "admin_action": log.admin_action,
                            "time_scanned": log.time_scanned.isoformat()
                            if log.time_scanned
                            else None,
                        }
                        for log in old_logs
                    ],
                },
                f,
                indent=2,
            )

        with get_session() as s:
            s.execute(delete(ActionLogs).where(ActionLogs.time_scanned < cutoff))
            s.commit()

        size_mb = round(archive_file.stat().st_size / 1024 / 1024, 2)
        logger.info(f"Archived {len(old_logs)} logs ({size_mb} MB)")


if __name__ == "__main__":
    archive_action_logs()
