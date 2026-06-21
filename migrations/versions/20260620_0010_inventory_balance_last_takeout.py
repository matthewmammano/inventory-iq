"""Add last_takeout_at to live inventory balances.

Revision ID: 20260620_0010
Revises: 20260619_0009
Create Date: 2026-06-20
"""

import sqlalchemy as sa
from alembic import op

revision = "20260620_0010"
down_revision = "20260619_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("inventory_balances")}
    if "last_takeout_at" in columns:
        return

    op.add_column("inventory_balances", sa.Column("last_takeout_at", sa.DateTime(), nullable=True))
    op.get_bind().execute(
        sa.text(
            """
            UPDATE inventory_balances
            SET last_takeout_at = (
                SELECT MAX(action_logs.time_scanned)
                FROM action_logs
                WHERE action_logs.agency_id = inventory_balances.agency_id
                  AND action_logs.item_id = inventory_balances.item_id
                  AND action_logs.operation_type = 'TAKEOUT'
                  AND action_logs.from_location_id = inventory_balances.storage_id
            )
            """
        )
    )


def downgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("inventory_balances")}
    if "last_takeout_at" in columns:
        op.drop_column("inventory_balances", "last_takeout_at")
