"""Move item UPCs into dedicated review tables.

Revision ID: 20260621_0011
Revises: 20260620_0010
Create Date: 2026-06-21
"""

import sqlalchemy as sa
from alembic import op

revision = "20260621_0011"
down_revision = "20260620_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TYPE alerttype ADD VALUE IF NOT EXISTS 'UNKNOWN_UPC'")

    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "item_upc_codes" not in tables:
        op.create_table(
            "item_upc_codes",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("agency_id", sa.Integer(), nullable=False),
            sa.Column("item_id", sa.Integer(), nullable=False),
            sa.Column("upc", sa.String(length=12), nullable=False),
            sa.ForeignKeyConstraint(["agency_id"], ["agencies.id"]),
            sa.ForeignKeyConstraint(["item_id"], ["items.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("agency_id", "upc", name="uq_item_upc_codes_agency_upc"),
        )
        op.create_index("ix_item_upc_codes_agency_id", "item_upc_codes", ["agency_id"])
        op.create_index("ix_item_upc_codes_item_id", "item_upc_codes", ["item_id"])
        op.create_index("idx_item_upc_codes_agency_item", "item_upc_codes", ["agency_id", "item_id"])
        op.create_index("idx_item_upc_codes_agency_upc", "item_upc_codes", ["agency_id", "upc"])

    if "unknown_upc_scans" not in tables:
        op.create_table(
            "unknown_upc_scans",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("agency_id", sa.Integer(), nullable=False),
            sa.Column("upc", sa.String(length=12), nullable=False),
            sa.Column("suggested_item_id", sa.Integer(), nullable=True),
            sa.Column("status", sa.Enum("PENDING", "RESOLVED", "IGNORE", name="unknownupcstatus"), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["agency_id"], ["agencies.id"]),
            sa.ForeignKeyConstraint(["suggested_item_id"], ["items.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("agency_id", "upc", name="uq_unknown_upc_scans_agency_upc"),
        )
        op.create_index("ix_unknown_upc_scans_agency_id", "unknown_upc_scans", ["agency_id"])
        op.create_index("ix_unknown_upc_scans_status", "unknown_upc_scans", ["status"])
        op.create_index("ix_unknown_upc_scans_created_at", "unknown_upc_scans", ["created_at"])
        op.create_index("idx_unknown_upc_scans_agency_status_created", "unknown_upc_scans", ["agency_id", "status", "created_at"])

    item_columns = {column["name"] for column in inspector.get_columns("items")}
    if "upc" in item_columns:
        op.execute(
            sa.text(
                """
                INSERT INTO item_upc_codes (agency_id, item_id, upc)
                SELECT agency_id, id, upc
                FROM items
                WHERE upc IS NOT NULL AND upc != ''
                """
            )
        )
        with op.batch_alter_table("items") as batch:
            batch.drop_index("idx_agency_upc")
            batch.drop_constraint("uq_items_agency_upc", type_="unique")
            batch.drop_column("upc")


def downgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("items")}
    if "upc" not in columns:
        with op.batch_alter_table("items") as batch:
            batch.add_column(sa.Column("upc", sa.String(length=12), nullable=True))
            batch.create_unique_constraint("uq_items_agency_upc", ["agency_id", "upc"])
            batch.create_index("idx_agency_upc", ["agency_id", "upc"])
        op.execute(
            sa.text(
                """
                UPDATE items
                SET upc = (
                    SELECT item_upc_codes.upc
                    FROM item_upc_codes
                    WHERE item_upc_codes.item_id = items.id
                    ORDER BY item_upc_codes.id
                    LIMIT 1
                )
                """
            )
        )

    op.drop_table("unknown_upc_scans")
    op.drop_table("item_upc_codes")
