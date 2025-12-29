"""
Simple database backup with 30-day retention.
Cron: 0 1 * * * python -m app.tasks.backup_database
"""

import gzip
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from loguru import logger

from app import create_app


def backup_database():
    """Create compressed daily backup and cleanup old ones"""
    app = create_app()
    with app.app_context():
        db_path = Path(app.instance_path) / "inventory_iq.db"
        backup_dir = Path(app.instance_path) / "backups"
        backup_dir.mkdir(exist_ok=True)

        if not db_path.exists():
            logger.warning("Database file not found")
            return

        # Create compressed backup
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = backup_dir / f"backup_{timestamp}.db.gz"

        with open(db_path, "rb") as f_in, gzip.open(backup_file, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)

        # Delete backups older than 30 days
        cutoff = datetime.now() - timedelta(days=30)
        deleted = 0
        for old_backup in backup_dir.glob("backup_*.db.gz"):
            if datetime.fromtimestamp(old_backup.stat().st_mtime) < cutoff:
                old_backup.unlink()
                deleted += 1

        size_mb = round(backup_file.stat().st_size / 1024 / 1024, 2)
        logger.info(
            f"Backup created: {backup_file.name} ({size_mb}MB), deleted {deleted} old backups"
        )


if __name__ == "__main__":
    backup_database()
