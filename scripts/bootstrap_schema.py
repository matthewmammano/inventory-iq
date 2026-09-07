"""Create database tables for local/dev deployments.

Production should use migrations once Alembic is introduced. This script keeps
schema creation explicit instead of hiding it inside web app startup.
"""

from pathlib import Path

from alembic import command
from alembic.config import Config

from app.shared.config import settings
from app.shared.database import create_all, init_db
from app.shared.logging import setup_logging
from app.shared.model_registry import import_model_modules
from app.shared.task_logging import logged_task

_REPO_ROOT = Path(__file__).resolve().parent.parent


def run() -> None:
    """Create all registered ORM tables if they do not already exist."""
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
        create_all()
        command.stamp(Config(str(_REPO_ROOT / "alembic.ini")), "head")


if __name__ == "__main__":
    run()
