"""Add admin soft-delete flags.

Revision ID: 20260624_0014
Revises: 20260623_0013
Create Date: 2026-06-24
"""

import sqlalchemy as sa
from alembic import op

revision = "20260624_0014"
down_revision = "20260623_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table_name in ("agency_emails", "agency_item_tags", "item_secondary_upcs"):
        with op.batch_alter_table(table_name) as batch:
            batch.add_column(sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade() -> None:
    for table_name in ("item_secondary_upcs", "agency_item_tags", "agency_emails"):
        with op.batch_alter_table(table_name) as batch:
            batch.drop_column("active")
