"""Add location filters to agency notification emails.

Revision ID: 20260525_0005
Revises: 20260515_0004
Create Date: 2026-05-25
"""

import sqlalchemy as sa
from alembic import op

revision = "20260525_0005"
down_revision = "20260515_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "location_filter_ids" in _columns():
        return
    with op.batch_alter_table("agency_emails") as batch_op:
        batch_op.add_column(sa.Column("location_filter_ids", sa.JSON(), nullable=True))


def downgrade() -> None:
    if "location_filter_ids" not in _columns():
        return
    with op.batch_alter_table("agency_emails") as batch_op:
        batch_op.drop_column("location_filter_ids")


def _columns() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {column["name"] for column in inspector.get_columns("agency_emails")}
