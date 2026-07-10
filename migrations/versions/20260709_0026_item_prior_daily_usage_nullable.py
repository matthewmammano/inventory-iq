"""Make items.prior_daily_usage nullable; no longer set through admin UI.

Revision ID: 20260709_0026
Revises: 20260708_0025
Create Date: 2026-07-09
"""

import sqlalchemy as sa
from alembic import op

revision = "20260709_0026"
down_revision = "20260708_0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("items") as batch_op:
        batch_op.alter_column("prior_daily_usage", existing_type=sa.Float(), nullable=True)


def downgrade() -> None:
    op.execute("UPDATE items SET prior_daily_usage = 0 WHERE prior_daily_usage IS NULL")
    with op.batch_alter_table("items") as batch_op:
        batch_op.alter_column("prior_daily_usage", existing_type=sa.Float(), nullable=False)
