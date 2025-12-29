"""
Archive action logs older than 1 year to JSON.
Cron: 0 4 1 * * python -m app.tasks.archive_action_logs
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from loguru import logger
from sqlalchemy import delete, select

from app import create_app
from app.db import get_session
from app.inventory.models import ActionLogs


def archive_action_logs():
    """Archive old logs to JSON and delete from database"""
    app = create_app()
    with app.app_context():
        cutoff_date = datetime.now(UTC) - timedelta(days=365)

        # Get logs to archive
        with get_session() as session:
            stmt = select(ActionLogs).where(ActionLogs.time_scanned < cutoff_date)
            old_logs = session.execute(stmt).scalars().all()

        if not old_logs:
            logger.info("No logs to archive")
            return

        # Create archive directory
        archive_dir = Path(app.instance_path) / "archives"
        archive_dir.mkdir(exist_ok=True)

        # Export to JSON
        timestamp = datetime.now().strftime("%Y%m%d")
        archive_file = archive_dir / f"action_logs_{timestamp}.json"

        logs_data = []
        for log in old_logs:
            logs_data.append(
                {
                    "id": log.id,
                    "user_id": log.user_id,
                    "item_id": log.item_id,
                    "operation_type": (
                        log.operation_type.value if log.operation_type else None
                    ),
                    "quantity_delta": log.quantity_delta,
                    "admin_action": log.admin_action,
                    "time_scanned": (
                        log.time_scanned.isoformat() if log.time_scanned else None
                    ),
                }
            )

        with open(archive_file, "w") as f:
            json.dump(
                {"archived_date": datetime.now().isoformat(), "logs": logs_data},
                f,
                indent=2,
            )

        # Delete archived logs from database
        with get_session() as session:
            del_stmt = delete(ActionLogs).where(ActionLogs.time_scanned < cutoff_date)
            session.execute(del_stmt)
            session.commit()

        size_mb = round(archive_file.stat().st_size / 1024 / 1024, 2)
        logger.info(
            f"Archived {len(old_logs)} logs to {archive_file.name} ({size_mb}MB)"
        )


if __name__ == "__main__":
    archive_action_logs()
