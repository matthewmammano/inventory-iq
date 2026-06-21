"""Add live inventory balances and supporting action-log indexes.

Revision ID: 20260619_0009
Revises: 20260526_0008
Create Date: 2026-06-19
"""

from collections import defaultdict

import sqlalchemy as sa
from alembic import op

revision = "20260619_0009"
down_revision = "20260526_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    tables = _tables()
    if "inventory_balances" not in tables:
        op.create_table(
            "inventory_balances",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("agency_id", sa.Integer(), nullable=False),
            sa.Column("item_id", sa.Integer(), nullable=False),
            sa.Column("storage_id", sa.Integer(), nullable=False),
            sa.Column("quantity", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_counted_at", sa.DateTime(), nullable=True),
            sa.Column("last_activity_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["agency_id"], ["agencies.id"]),
            sa.ForeignKeyConstraint(["item_id"], ["items.id"]),
            sa.ForeignKeyConstraint(["storage_id"], ["agency_storages.id"]),
            sa.UniqueConstraint("agency_id", "item_id", "storage_id", name="uq_inventory_balances_agency_item_storage"),
        )
        op.create_index("idx_inventory_balances_agency_storage", "inventory_balances", ["agency_id", "storage_id"])
        op.create_index("idx_inventory_balances_agency_item", "inventory_balances", ["agency_id", "item_id"])
        _backfill_inventory_balances()

    indexes = _indexes("action_logs")
    if "idx_action_logs_agency_item_time_id" not in indexes:
        op.create_index(
            "idx_action_logs_agency_item_time_id",
            "action_logs",
            ["agency_id", "item_id", "time_scanned", "id"],
        )
    if "idx_action_logs_agency_to_operation_time_id" not in indexes:
        op.create_index(
            "idx_action_logs_agency_to_operation_time_id",
            "action_logs",
            ["agency_id", "to_location_id", "operation_type", "time_scanned", "id"],
        )
    if "idx_action_logs_agency_from_operation_time_id" not in indexes:
        op.create_index(
            "idx_action_logs_agency_from_operation_time_id",
            "action_logs",
            ["agency_id", "from_location_id", "operation_type", "time_scanned", "id"],
        )
    if "idx_action_logs_agency_id_desc" not in indexes:
        op.create_index("idx_action_logs_agency_id_desc", "action_logs", ["agency_id", "id"])


def downgrade() -> None:
    indexes = _indexes("action_logs")
    if "idx_action_logs_agency_id_desc" in indexes:
        op.drop_index("idx_action_logs_agency_id_desc", table_name="action_logs")
    if "idx_action_logs_agency_from_operation_time_id" in indexes:
        op.drop_index("idx_action_logs_agency_from_operation_time_id", table_name="action_logs")
    if "idx_action_logs_agency_to_operation_time_id" in indexes:
        op.drop_index("idx_action_logs_agency_to_operation_time_id", table_name="action_logs")
    if "idx_action_logs_agency_item_time_id" in indexes:
        op.drop_index("idx_action_logs_agency_item_time_id", table_name="action_logs")

    if "inventory_balances" in _tables():
        op.drop_index("idx_inventory_balances_agency_item", table_name="inventory_balances")
        op.drop_index("idx_inventory_balances_agency_storage", table_name="inventory_balances")
        op.drop_table("inventory_balances")


def _backfill_inventory_balances() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            """
            SELECT agency_id, item_id, operation_type, from_location_id, to_location_id, quantity_delta, time_scanned
            FROM action_logs
            WHERE item_id IS NOT NULL
            ORDER BY agency_id, item_id, time_scanned, id
            """
        )
    ).mappings()
    states: dict[tuple[int, int, int], dict[str, int | None]] = defaultdict(
        lambda: {"quantity": 0, "last_counted_at": None, "last_activity_at": None}
    )
    for row in rows:
        agency_id = int(row["agency_id"])
        item_id = int(row["item_id"])
        quantity = int(row["quantity_delta"])
        scanned_at = row["time_scanned"]
        operation_type = str(row["operation_type"])
        from_storage_id = row["from_location_id"]
        to_storage_id = row["to_location_id"]

        if operation_type == "COUNT" and to_storage_id is not None:
            state = states[(agency_id, item_id, int(to_storage_id))]
            state["quantity"] = quantity
            state["last_counted_at"] = scanned_at
            state["last_activity_at"] = scanned_at
            continue
        if to_storage_id is not None:
            state = states[(agency_id, item_id, int(to_storage_id))]
            state["quantity"] = int(state["quantity"] or 0) + quantity
            state["last_activity_at"] = scanned_at
        if from_storage_id is not None:
            state = states[(agency_id, item_id, int(from_storage_id))]
            state["quantity"] = int(state["quantity"] or 0) - quantity
            state["last_activity_at"] = scanned_at

    if not states:
        return

    now = bind.execute(sa.text("SELECT CURRENT_TIMESTAMP")).scalar_one()
    payload = [
        {
            "agency_id": agency_id,
            "item_id": item_id,
            "storage_id": storage_id,
            "quantity": int(state["quantity"] or 0),
            "last_counted_at": state["last_counted_at"],
            "last_activity_at": state["last_activity_at"],
            "updated_at": now,
        }
        for (agency_id, item_id, storage_id), state in states.items()
    ]
    inventory_balances = sa.table(
        "inventory_balances",
        sa.column("agency_id", sa.Integer()),
        sa.column("item_id", sa.Integer()),
        sa.column("storage_id", sa.Integer()),
        sa.column("quantity", sa.Integer()),
        sa.column("last_counted_at", sa.DateTime()),
        sa.column("last_activity_at", sa.DateTime()),
        sa.column("updated_at", sa.DateTime()),
    )
    op.bulk_insert(inventory_balances, payload)


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _indexes(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {str(index["name"]) for index in inspector.get_indexes(table_name)}
