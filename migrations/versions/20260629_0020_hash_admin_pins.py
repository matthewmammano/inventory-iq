"""Hash admin PINs in place.

Revision ID: 20260629_0020
Revises: 20260628_0019
Create Date: 2026-06-29
"""

import sqlalchemy as sa
from alembic import op
from werkzeug.security import generate_password_hash

revision = "20260629_0020"
down_revision = "20260628_0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "agencies" not in tables:
        return

    columns = {column["name"] for column in inspector.get_columns("agencies")}
    if "pin" in columns:
        with op.batch_alter_table("agencies") as batch_op:
            batch_op.alter_column("pin", existing_type=sa.String(length=4), type_=sa.Text(), existing_nullable=False, nullable=False)
        rows = bind.execute(sa.text("SELECT id, pin FROM agencies WHERE pin IS NOT NULL AND TRIM(pin) <> ''")).mappings()
        for row in rows:
            bind.execute(
                sa.text("UPDATE agencies SET pin = :pin WHERE id = :agency_id"),
                {"agency_id": row["id"], "pin": generate_password_hash(row["pin"])},
            )


def downgrade() -> None:
    raise RuntimeError("Downgrade is not supported because plaintext admin PINs cannot be reconstructed from hashes.")
