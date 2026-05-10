"""store raw confidence as float

Revision ID: 20260510_0002
Revises: 20260510_0001
Create Date: 2026-05-10
"""

import sqlalchemy as sa
from alembic import op

revision = "20260510_0002"
down_revision = "20260510_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("inventory_trends") as batch_op:
        batch_op.alter_column(
            "confidence_percent",
            existing_type=sa.Integer(),
            type_=sa.Float(),
            existing_nullable=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("inventory_trends") as batch_op:
        batch_op.alter_column(
            "confidence_percent",
            existing_type=sa.Float(),
            type_=sa.Integer(),
            existing_nullable=True,
        )
