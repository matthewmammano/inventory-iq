"""Normalize local SQLite seed databases to the current schema shape.

This is a local maintenance utility for seed artifacts under ``tmp/seed``.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import cast

from loguru import logger
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session
from sqlalchemy.schema import Index, Table

from app.inventory.balance_service import rebuild_inventory_balances
from app.inventory.models import ActionLogs, InventoryBalances
from app.shared.config import settings
from app.shared.logging import setup_logging
from app.shared.model_registry import import_model_modules
from app.shared.task_logging import logged_task

HEAD_REVISION = "20260620_0010"
DEFAULT_SEED_DIR = Path("tmp/seed")
ACTION_LOG_INDEX_NAMES = {
    "idx_action_logs_agency_item_time_id",
    "idx_action_logs_agency_to_operation_time_id",
    "idx_action_logs_agency_from_operation_time_id",
    "idx_action_logs_agency_id_desc",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Normalize local SQLite seed DB files.")
    parser.add_argument("paths", nargs="*", type=Path, help="Seed DB files to normalize. Defaults to tmp/seed/*.db")
    return parser.parse_args()


def main() -> None:
    setup_logging(debug=settings.debug, json_logs=settings.is_prod)
    args = parse_args()
    paths = args.paths or sorted(DEFAULT_SEED_DIR.glob("*.db"))
    if not paths:
        raise SystemExit("No seed DB files found.")
    with logged_task("admin_cli.normalize_seed_databases", actor="cli", admin_action=True, database_count=len(paths)) as result:
        normalized = 0
        for path in paths:
            normalize_seed_database(path.resolve())
            normalized += 1
        result["normalized_count"] = normalized


def normalize_seed_database(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(path)

    import_model_modules()
    engine = create_engine(f"sqlite:///{path.as_posix()}", future=True)
    with engine.begin() as connection:
        _ensure_inventory_balances(connection)
        _ensure_action_log_indexes(connection)
        _ensure_alembic_version_table(connection)

    with Session(engine, future=True) as session:
        rebuilt_rows = rebuild_inventory_balances(session)
        _stamp_head_revision(session)
        session.commit()

    logger.debug("Seed database normalized", extra={"path": str(path), "rebuilt_row_count": rebuilt_rows, "revision": HEAD_REVISION})


def _ensure_inventory_balances(connection) -> None:
    inspector = inspect(connection)
    if "inventory_balances" not in inspector.get_table_names():
        inventory_balances_table = cast(Table, InventoryBalances.__table__)
        inventory_balances_table.create(bind=connection, checkfirst=True)
        return

    columns = {column["name"] for column in inspector.get_columns("inventory_balances")}
    if "last_takeout_at" not in columns:
        connection.execute(text("ALTER TABLE inventory_balances ADD COLUMN last_takeout_at DATETIME"))


def _ensure_action_log_indexes(connection) -> None:
    existing = {index["name"] for index in inspect(connection).get_indexes("action_logs")}
    action_logs_table = cast(Table, ActionLogs.__table__)
    for index in cast(set[Index], action_logs_table.indexes):
        if index.name not in ACTION_LOG_INDEX_NAMES or index.name in existing:
            continue
        index.create(bind=connection, checkfirst=True)


def _ensure_alembic_version_table(connection) -> None:
    connection.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS alembic_version (
                version_num VARCHAR(32) NOT NULL PRIMARY KEY
            )
            """
        )
    )


def _stamp_head_revision(session: Session) -> None:
    session.execute(text("DELETE FROM alembic_version"))
    session.execute(text("INSERT INTO alembic_version (version_num) VALUES (:version_num)"), {"version_num": HEAD_REVISION})


if __name__ == "__main__":
    main()
