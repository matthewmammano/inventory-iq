"""Create or upgrade the database schema for any environment.

Runs the same `alembic upgrade head` production runs, so dev and prod can never
drift apart. Schema creation stays explicit rather than hiding inside app startup.
"""

from pathlib import Path

from alembic import command
from alembic.config import Config

from app.shared.config import settings
from app.shared.database import init_db
from app.shared.logging import setup_logging
from app.shared.model_registry import import_model_modules
from app.shared.task_logging import logged_task

_REPO_ROOT = Path(__file__).resolve().parent.parent


def run() -> None:
    """Bring the configured database up to the latest migration."""
    setup_logging(json_logs=settings.is_prod)
    with logged_task(
        "admin_cli.bootstrap_schema",
        actor="cli",
        admin_action=True,
        database=settings.database_url.split("://")[0] if "://" in settings.database_url else "unknown",
    ) as result:
        import_model_modules()
        if settings.database_url.startswith("sqlite:///"):
            db_path = Path(settings.database_url.removeprefix("sqlite:///"))
            db_path.parent.mkdir(parents=True, exist_ok=True)
            result["sqlite_path"] = str(db_path)

        init_db(settings.database_url)
        command.upgrade(Config(str(_REPO_ROOT / "alembic.ini")), "head")


if __name__ == "__main__":
    run()
