"""Add per-item guest quick-adjust opt-in.

Revision ID: 20260526_0008
Revises: 20260525_0007
Create Date: 2026-05-26
"""

import sqlalchemy as sa
from alembic import op

revision = "20260526_0008"
down_revision = "20260525_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("items")}
    if "guest_quick_adjust" in columns:
        return
    op.add_column(
        "items",
        sa.Column(
            "guest_quick_adjust",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("items")}
    if "guest_quick_adjust" not in columns:
        return
    op.drop_column("items", "guest_quick_adjust")
