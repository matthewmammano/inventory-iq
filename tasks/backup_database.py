"""Create compressed daily backup with 30-day retention.
Cron: 0 1 * * * python tasks/backup_database.py
"""

import gzip
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from loguru import logger

from app import create_app


def backup_database() -> None:
    app = create_app()
    with app.app_context():
        db_path = Path(app.instance_path) / "inventory_iq.db"
        backup_dir = Path(app.instance_path) / "backups"
        backup_dir.mkdir(exist_ok=True)

        if not db_path.exists():
            logger.warning("Database file not found")
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = backup_dir / f"backup_{timestamp}.db.gz"

        with db_path.open("rb") as f_in, gzip.open(backup_file, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)

        cutoff = datetime.now() - timedelta(days=30)
        deleted = 0
        for backup in backup_dir.glob("backup_*.db.gz"):
            if datetime.fromtimestamp(backup.stat().st_mtime) >= cutoff:
                continue
            backup.unlink()
            deleted += 1

        size_mb = round(backup_file.stat().st_size / 1024 / 1024, 2)
        logger.info(f"Backup: {backup_file.name} ({size_mb} MB), deleted {deleted} old backups")


if __name__ == "__main__":
    backup_database()
