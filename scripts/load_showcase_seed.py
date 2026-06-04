"""Replace the configured database with a SQLite seed database."""

import argparse
import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger
from sqlalchemy import JSON, Boolean, DateTime, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.sql.schema import Column, Table

from app.alerts import models as _alert_models  # noqa: F401
from app.auth import models as _auth_models  # noqa: F401
from app.inventory import models as _inventory_models  # noqa: F401
from app.prediction import models as _prediction_models  # noqa: F401
from app.shared import models as _shared_models  # noqa: F401
from app.shared.config import settings
from app.shared.database import Base, normalize_database_url


def main() -> None:
    parser = argparse.ArgumentParser(description="Load a SQLite seed DB into the configured DB.")
    parser.add_argument("seed_db", type=Path, help="SQLite seed database file")
    parser.add_argument("--replace", action="store_true", help="replace the target database")
    parser.add_argument("--yes", action="store_true", help="confirm destructive replacement")
    args = parser.parse_args()

    if not args.replace or not args.yes:
        raise SystemExit("Use --replace --yes to replace the configured database.")
    if not args.seed_db.exists():
        raise SystemExit(f"Seed DB not found: {args.seed_db}")

    database_url = normalize_database_url(settings.database_url)
    if _copy_sqlite_seed(args.seed_db, database_url):
        return
    _load_seed_rows(args.seed_db, database_url)


def _copy_sqlite_seed(seed_db: Path, database_url: str) -> bool:
    url = make_url(database_url)
    if not url.drivername.startswith("sqlite"):
        return False
    if not url.database or url.database == ":memory:":
        raise SystemExit("Cannot replace an in-memory SQLite database.")

    target_path = Path(url.database)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(seed_db, target_path)
    logger.info(f"Seed DB copied to SQLite database: seed={seed_db} target={target_path}")
    return True


def _load_seed_rows(seed_db: Path, database_url: str) -> None:
    engine = create_engine(database_url, future=True)
    with engine.begin() as target:
        Base.metadata.drop_all(bind=target)
        Base.metadata.create_all(bind=target)
        with sqlite3.connect(seed_db) as source:
            source.row_factory = sqlite3.Row
            for table in Base.metadata.sorted_tables:
                rows = _seed_rows(source, table)
                if rows:
                    target.execute(table.insert(), rows)
                _reset_postgres_sequence(target, table)
                logger.info(f"Seed table loaded: table={table.name} rows={len(rows)}")
    logger.info(f"Seed DB loaded into configured database: seed={seed_db} dialect={engine.dialect.name}")


def _seed_rows(source: sqlite3.Connection, table: Table) -> list[dict[str, Any]]:
    rows = source.execute(f'SELECT * FROM "{table.name}"').fetchall()
    return [{column.name: _column_value(column, row[column.name]) for column in table.columns} for row in rows]


def _column_value(column: Column[Any], value: Any) -> Any:
    if value is None:
        return None
    if isinstance(column.type, Boolean):
        return bool(value)
    if isinstance(column.type, DateTime) and isinstance(value, str):
        return datetime.fromisoformat(value)
    if isinstance(column.type, JSON) and isinstance(value, str):
        return json.loads(value)
    return value


def _reset_postgres_sequence(target: Any, table: Table) -> None:
    if target.dialect.name != "postgresql":
        return
    primary_key = next(iter(table.primary_key.columns), None)
    if primary_key is None:
        return
    target.execute(
        text(
            "SELECT setval(pg_get_serial_sequence(:table_name, :column_name), "
            f"COALESCE((SELECT MAX({primary_key.name}) FROM {table.name}), 1), true)"
        ),
        {"table_name": table.name, "column_name": primary_key.name},
    )


if __name__ == "__main__":
    main()
