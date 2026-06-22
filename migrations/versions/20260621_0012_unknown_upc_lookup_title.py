"""Store UPC lookup title suggestions.

Revision ID: 20260621_0012
Revises: 20260621_0011
Create Date: 2026-06-21
"""

import sqlalchemy as sa
from alembic import op

revision = "20260621_0012"
down_revision = "20260621_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("unknown_upc_scans")}
    if "lookup_title" not in columns:
        op.add_column("unknown_upc_scans", sa.Column("lookup_title", sa.String(length=255), nullable=True))


def downgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("unknown_upc_scans")}
    if "lookup_title" in columns:
        op.drop_column("unknown_upc_scans", "lookup_title")
