"""v1 schema baseline.

Creates the full current schema for fresh databases. Future migrations should
make explicit incremental changes instead of editing this baseline.

Revision ID: 20260510_0001
Revises:
Create Date: 2026-05-10
"""

from alembic import op

from app.alerts import models as _alert_models  # noqa: F401
from app.auth import models as _auth_models  # noqa: F401
from app.inventory import models as _inventory_models  # noqa: F401
from app.shared.database import Base

revision = "20260510_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
