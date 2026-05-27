"""Backfill generated UPCs for existing items.

Revision ID: 20260525_0007
Revises: 20260525_0006
Create Date: 2026-05-25
"""

import sqlalchemy as sa
from alembic import op

revision = "20260525_0007"
down_revision = "20260525_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    items = sa.table("items", sa.column("id", sa.Integer), sa.column("upc", sa.String))
    connection = op.get_bind()
    rows = connection.execute(sa.select(items.c.id).where(items.c.upc.is_(None))).all()
    for (item_id,) in rows:
        connection.execute(
            items.update().where(items.c.id == item_id).values(upc=_generated_upc_from_id(item_id))
        )


def downgrade() -> None:
    pass


def _generated_upc_from_id(item_id: int) -> str:
    base = f"5{item_id:0>10}"
    return base + _check_digit(base)


def _check_digit(upc11: str) -> str:
    digits = [int(digit) for digit in upc11]
    total = sum(digits[::2]) * 3 + sum(digits[1::2])
    return str((10 - total % 10) % 10)
