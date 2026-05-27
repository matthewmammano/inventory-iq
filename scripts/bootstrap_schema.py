"""Create database tables for local/dev deployments.

Production should use migrations once Alembic is introduced. This script keeps
schema creation explicit instead of hiding it inside web app startup.
"""

from pathlib import Path

from loguru import logger

from app.alerts import models as _alert_models  # noqa: F401 - register ORM models
from app.auth import models as _auth_models  # noqa: F401 - register ORM models
from app.inventory import models as _inventory_models  # noqa: F401 - register ORM models
from app.prediction import models as _prediction_models  # noqa: F401 - register ORM models
from app.shared import models as _shared_models  # noqa: F401 - register ORM models
from app.shared.config import settings
from app.shared.database import create_all, init_db


def run() -> None:
    """Create all registered ORM tables if they do not already exist."""
    if settings.database_url.startswith("sqlite:///"):
        db_path = Path(settings.database_url.removeprefix("sqlite:///"))
        db_path.parent.mkdir(parents=True, exist_ok=True)

    init_db(settings.database_url)
    create_all()
    logger.info("Database schema ready", extra={"database_url": settings.database_url})


if __name__ == "__main__":
    run()
