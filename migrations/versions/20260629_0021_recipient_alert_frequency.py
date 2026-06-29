"""Add per-recipient alert email frequency.

Revision ID: 20260629_0021
Revises: 20260629_0020
Create Date: 2026-06-29
"""

import sqlalchemy as sa
from alembic import op

revision = "20260629_0021"
down_revision = "20260629_0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "agency_emails" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("agency_emails")}
    if "alert_frequency" in columns:
        return
    with op.batch_alter_table("agency_emails") as batch_op:
        batch_op.add_column(sa.Column("alert_frequency", sa.String(length=16), nullable=False, server_default="HOURLY"))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "agency_emails" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("agency_emails")}
    if "alert_frequency" not in columns:
        return
    with op.batch_alter_table("agency_emails") as batch_op:
        batch_op.drop_column("alert_frequency")
