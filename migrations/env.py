"""Alembic runtime environment.

Alembic runs this file for every migration command. The model imports below are
intentional: they register ORM metadata before autogenerate/create_all logic.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.alerts import models as _alert_models  # noqa: F401
from app.auth import models as _auth_models  # noqa: F401
from app.inventory import models as _inventory_models  # noqa: F401
from app.prediction import models as _prediction_models  # noqa: F401
from app.shared import models as _shared_models  # noqa: F401
from app.shared.config import settings
from app.shared.database import Base, normalize_database_url

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    return normalize_database_url(settings.database_url).replace("%", "%%")


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _database_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
