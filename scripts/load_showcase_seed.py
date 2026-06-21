"""Replace the configured database with a SQLite seed database."""

import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger
from sqlalchemy import JSON, Boolean, DateTime, create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.sql.schema import Column, Table

from app.inventory.balance_service import rebuild_inventory_balances
from app.shared.config import settings
from app.shared.database import Base, normalize_database_url
from app.shared.logging import setup_logging
from app.shared.model_registry import import_model_modules
from app.shared.task_logging import logged_task


def main() -> None:
    setup_logging(debug=settings.debug, json_logs=settings.is_prod)
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
    _load_seed_rows(args.seed_db, database_url)


def _load_seed_rows(seed_db: Path, database_url: str) -> None:
    import_model_modules()
    engine = create_engine(database_url, future=True)
    with logged_task(
        "admin_cli.load_showcase_seed",
        actor="cli",
        admin_action=True,
        seed=str(seed_db),
        dialect=engine.dialect.name,
    ) as result:
        table_count = 0
        row_count = 0
        with engine.begin() as target:
            logger.debug("Showcase seed target schema reset", extra={"dialect": engine.dialect.name})
            Base.metadata.drop_all(bind=target)
            Base.metadata.create_all(bind=target)
            with sqlite3.connect(seed_db) as source:
                source.row_factory = sqlite3.Row
                for table in Base.metadata.sorted_tables:
                    rows = _seed_rows(source, table)
                    if rows:
                        target.execute(table.insert(), rows)
                    _reset_postgres_sequence(target, table)
                    table_count += 1
                    row_count += len(rows)
                    logger.debug("Showcase seed table loaded", extra={"table": table.name, "rows": len(rows)})
            session = Session(bind=target, future=True)
            try:
                rebuild_inventory_balances(session)
                session.flush()
            finally:
                session.close()
        result.update({"table_count": table_count, "row_count": row_count})


def _seed_rows(source: sqlite3.Connection, table: Table) -> list[dict[str, Any]]:
    if not _source_has_table(source, table.name):
        return []
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
            f"SELECT setval(pg_get_serial_sequence(:table_name, :column_name), COALESCE((SELECT MAX({primary_key.name}) FROM {table.name}), 1), true)"
        ),
        {"table_name": table.name, "column_name": primary_key.name},
    )


def _source_has_table(source: sqlite3.Connection, table_name: str) -> bool:
    row = source.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


if __name__ == "__main__":
    main()
