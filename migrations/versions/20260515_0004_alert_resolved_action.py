"""Add resolved alert lifecycle state.

Revision ID: 20260515_0004
Revises: 20260514_0003
Create Date: 2026-05-15
"""

from alembic import op

revision = "20260515_0004"
down_revision = "20260514_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TYPE alertaction ADD VALUE IF NOT EXISTS 'RESOLVED'")


def downgrade() -> None:
    # PostgreSQL enum values cannot be safely removed without rebuilding the type.
    pass
