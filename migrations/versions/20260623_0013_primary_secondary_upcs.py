"""Split primary/secondary UPCs and tidy SQLite column order.

Revision ID: 20260623_0013
Revises: 20260621_0012
Create Date: 2026-06-23
"""

import sqlalchemy as sa
from alembic import op

revision = "20260623_0013"
down_revision = "20260621_0012"
branch_labels = None
depends_on = None

PREFIX = "042"

TABLE_ORDERS = {
    "agencies": (
        "id",
        "display_name",
        "email",
        "active",
        "image",
        "timezone",
        "password",
        "pin",
        "user_count_allow",
        "user_restock_allow",
        "lead_time_days",
        "count_last_days",
        "alert_rare_scan_days",
        "notes",
        "created_at",
    ),
    "agency_devices": (
        "id",
        "agency_id",
        "agency_location_id",
        "device_token_hash",
        "active",
        "created_at",
        "updated_at",
        "last_seen_at",
    ),
    "agency_emails": (
        "id",
        "agency_id",
        "email",
        "location_filter_ids",
        "alert_for_stockout",
        "alert_for_stockout_pred",
        "alert_for_low",
        "alert_for_low_pred",
        "alert_for_stale_count",
        "alert_for_rare_takeout",
        "alert_for_count",
        "alert_for_restock",
        "alert_for_takeout",
        "alert_for_transfer",
        "daily_summary",
        "weekly_summary",
        "monthly_summary",
        "yearly_summary",
    ),
    "agency_item_tags": ("id", "agency_id", "tag_name", "color"),
    "agency_locations": ("id", "agency_id", "name"),
    "agency_storages": ("id", "agency_id", "location_id", "name", "user_access_from", "user_access_to"),
    "alert_records": ("id", "agency_id", "agency_email_id", "type", "action", "details_json", "created_at", "action_at"),
    "inventory_trends": (
        "id",
        "agency_id",
        "item_id",
        "agency_location_id",
        "trend_per_day",
        "confidence_percent",
        "segment_count",
        "data_signature",
        "trained_at",
    ),
    "items": (
        "id",
        "agency_id",
        "name",
        "upc",
        "active",
        "guest_quick_adjust",
        "increments",
        "tag_ids",
        "image",
        "min_quantity",
        "max_quantity",
        "batch_size",
        "restock_delivery_days",
        "prior_daily_usage",
        "last_accessed",
    ),
    "item_secondary_upcs": ("id", "agency_id", "item_id", "upc"),
    "unknown_upc_scans": ("id", "agency_id", "upc", "status", "suggested_item_id", "lookup_title", "created_at", "updated_at"),
    "action_logs": (
        "id",
        "agency_id",
        "item_id",
        "operation_type",
        "quantity_delta",
        "from_location_id",
        "to_location_id",
        "admin_action",
        "time_scanned",
    ),
    "inventory_balances": (
        "id",
        "agency_id",
        "item_id",
        "storage_id",
        "quantity",
        "last_counted_at",
        "last_activity_at",
        "last_takeout_at",
        "updated_at",
    ),
    "password_reset_pins": ("id", "agency_id", "pin_hash", "attempt_count", "expires_at", "used_at", "created_at"),
    "scheduler_runs": ("id", "agency_id", "job_name", "period_key", "status", "started_at", "finished_at", "error"),
}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    item_columns = {column["name"] for column in inspector.get_columns("items")}

    if "upc" not in item_columns:
        with op.batch_alter_table("items") as batch:
            batch.add_column(sa.Column("upc", sa.String(length=12), nullable=True))

    _backfill_primary_upcs(bind, tables)
    _ensure_item_upc_constraints(inspector)
    _ensure_secondary_table(tables)
    _copy_old_upcs_to_secondary(tables)
    if "item_upc_codes" in tables:
        op.drop_table("item_upc_codes")
    _reorder_sqlite_tables()


def downgrade() -> None:
    if "item_upc_codes" not in set(sa.inspect(op.get_bind()).get_table_names()):
        op.create_table(
            "item_upc_codes",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("agency_id", sa.Integer(), nullable=False),
            sa.Column("item_id", sa.Integer(), nullable=False),
            sa.Column("upc", sa.String(length=12), nullable=False),
            sa.ForeignKeyConstraint(["agency_id"], ["agencies.id"]),
            sa.ForeignKeyConstraint(["item_id"], ["items.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("agency_id", "upc", name="uq_item_upc_codes_agency_upc"),
        )
    op.execute(
        sa.text(
            """
            INSERT INTO item_upc_codes (agency_id, item_id, upc)
            SELECT agency_id, item_id, upc FROM item_secondary_upcs
            """
        )
    )
    op.drop_table("item_secondary_upcs")
    with op.batch_alter_table("items") as batch:
        batch.drop_index("idx_agency_upc")
        batch.drop_constraint("uq_items_agency_upc", type_="unique")
        batch.drop_constraint("ck_items_upc_private_prefix", type_="check")
        batch.drop_column("upc")


def _ensure_secondary_table(tables: set[str]) -> None:
    if "item_secondary_upcs" in tables:
        return
    op.create_table(
        "item_secondary_upcs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agency_id", sa.Integer(), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("upc", sa.String(length=12), nullable=False),
        sa.CheckConstraint(f"upc NOT LIKE '{PREFIX}%'", name="ck_item_secondary_upcs_not_private_prefix"),
        sa.ForeignKeyConstraint(["agency_id"], ["agencies.id"]),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("agency_id", "upc", name="uq_item_secondary_upcs_agency_upc"),
    )
    op.create_index("ix_item_secondary_upcs_agency_id", "item_secondary_upcs", ["agency_id"])
    op.create_index("ix_item_secondary_upcs_item_id", "item_secondary_upcs", ["item_id"])
    op.create_index("idx_item_secondary_upcs_agency_item", "item_secondary_upcs", ["agency_id", "item_id"])
    op.create_index("idx_item_secondary_upcs_agency_upc", "item_secondary_upcs", ["agency_id", "upc"])


def _reorder_sqlite_tables() -> None:
    if op.get_bind().dialect.name != "sqlite":
        return
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    for table_name, column_order in TABLE_ORDERS.items():
        if table_name not in tables:
            continue
        with op.batch_alter_table(table_name, recreate="always", partial_reordering=[column_order]):
            pass


def _copy_old_upcs_to_secondary(tables: set[str]) -> None:
    if "item_upc_codes" not in tables:
        return
    op.execute(
        sa.text(
            f"""
            INSERT INTO item_secondary_upcs (agency_id, item_id, upc)
            SELECT old.agency_id, old.item_id, old.upc
            FROM item_upc_codes old
            JOIN items ON items.id = old.item_id
            LEFT JOIN item_secondary_upcs existing
              ON existing.agency_id = old.agency_id AND existing.upc = old.upc
            WHERE old.upc NOT LIKE '{PREFIX}%'
              AND old.upc != items.upc
              AND existing.id IS NULL
            """
        )
    )


def _ensure_item_upc_constraints(inspector) -> None:
    indexes = {index["name"] for index in inspector.get_indexes("items")}
    uniques = {constraint["name"] for constraint in inspector.get_unique_constraints("items")}
    checks = {constraint["name"] for constraint in inspector.get_check_constraints("items")}
    with op.batch_alter_table("items") as batch:
        if "uq_items_agency_upc" not in uniques:
            batch.create_unique_constraint("uq_items_agency_upc", ["agency_id", "upc"])
        if "ck_items_upc_private_prefix" not in checks:
            batch.create_check_constraint("ck_items_upc_private_prefix", f"upc LIKE '{PREFIX}%'")
        if "idx_agency_upc" not in indexes:
            batch.create_index("idx_agency_upc", ["agency_id", "upc"])
        batch.alter_column("upc", existing_type=sa.String(length=12), nullable=False)


def _backfill_primary_upcs(bind, tables: set[str]) -> None:
    items = sa.table("items", sa.column("id", sa.Integer), sa.column("agency_id", sa.Integer), sa.column("upc", sa.String))
    for item_id, agency_id, upc in bind.execute(sa.select(items.c.id, items.c.agency_id, items.c.upc)).all():
        if upc and upc.startswith(PREFIX):
            continue
        bind.execute(items.update().where(items.c.id == item_id).values(upc=_unique_private_upc(bind, tables, agency_id, item_id)))


def _unique_private_upc(bind, tables: set[str], agency_id: int, item_id: int) -> str:
    for salt in range(1000):
        body = f"{PREFIX}{(item_id + salt) % 100000000:08d}"
        upc = body + _check_digit(body)
        if not _upc_exists(bind, tables, agency_id, upc):
            return upc
    raise RuntimeError("Could not generate unique private UPC.")


def _upc_exists(bind, tables: set[str], agency_id: int, upc: str) -> bool:
    params = {"agency_id": agency_id, "upc": upc}
    if bind.execute(sa.text("SELECT 1 FROM items WHERE agency_id = :agency_id AND upc = :upc"), params).first():
        return True
    return any(
        bind.execute(sa.text(f"SELECT 1 FROM {table} WHERE agency_id = :agency_id AND upc = :upc"), params).first()
        for table in ("item_upc_codes", "item_secondary_upcs")
        if table in tables
    )


def _check_digit(upc11: str) -> str:
    digits = [int(digit) for digit in upc11]
    total = sum(digits[::2]) * 3 + sum(digits[1::2])
    return str((10 - total % 10) % 10)
