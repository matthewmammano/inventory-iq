"""
Archive action logs older than 1 year to JSON.
Cron: 0 4 1 * * python -m app.tasks.archive_action_logs
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from app import create_app, db
from app.inventory.models import ActionLogs

def archive_action_logs():
    """Archive old logs to JSON and delete from database"""
    app = create_app()
    with app.app_context():
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=365)

        # Get logs to archive
        old_logs = ActionLogs.query.filter(ActionLogs.time_scanned < cutoff_date).all()

        if not old_logs:
            print("No logs to archive")
            return

        # Create archive directory
        archive_dir = Path(app.instance_path) / "archives"
        archive_dir.mkdir(exist_ok=True)

        # Export to JSON
        timestamp = datetime.now().strftime("%Y%m%d")
        archive_file = archive_dir / f"action_logs_{timestamp}.json"

        logs_data = []
        for log in old_logs:
            logs_data.append({
                "id": log.id,
                "user_id": log.user_id,
                "item_id": log.item_id,
                "operation_type": log.operation_type.value if log.operation_type else None,
                "quantity_delta": log.quantity_delta,
                "admin_action": log.admin_action,
                "time_scanned": log.time_scanned.isoformat() if log.time_scanned else None
            })

        with open(archive_file, 'w') as f:
            json.dump({"archived_date": datetime.now().isoformat(), "logs": logs_data}, f, indent=2)

        # Delete from database
        ActionLogs.query.filter(ActionLogs.time_scanned < cutoff_date).delete()
        db.session.commit()

        size_mb = round(archive_file.stat().st_size / 1024 / 1024, 2)
        print(f"Archived {len(old_logs)} logs to {archive_file.name} ({size_mb}MB)")

if __name__ == "__main__":
    archive_action_logs()