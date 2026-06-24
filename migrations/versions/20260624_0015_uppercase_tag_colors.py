"""Normalize tag colors to uppercase.

Revision ID: 20260624_0015
Revises: 20260624_0014
Create Date: 2026-06-24
"""

import sqlalchemy as sa
from alembic import op

revision = "20260624_0015"
down_revision = "20260624_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text("UPDATE agency_item_tags SET color = UPPER(color) WHERE color IS NOT NULL"))


def downgrade() -> None:
    pass
