"""Add per-item scan-alert flag and per-recipient scan-alert scope.

Revision ID: 20260723_0027
Revises: 20260709_0026
Create Date: 2026-07-23
"""

import sqlalchemy as sa
from alembic import op

revision = "20260723_0027"
down_revision = "20260709_0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("items") as batch_op:
        batch_op.add_column(sa.Column("scan_alert_flagged", sa.Boolean(), nullable=False, server_default=sa.false()))
    with op.batch_alter_table("notification_recipients") as batch_op:
        batch_op.add_column(sa.Column("scan_alert_scope", sa.String(length=16), nullable=False, server_default="ALL"))


def downgrade() -> None:
    with op.batch_alter_table("notification_recipients") as batch_op:
        batch_op.drop_column("scan_alert_scope")
    with op.batch_alter_table("items") as batch_op:
        batch_op.drop_column("scan_alert_flagged")
