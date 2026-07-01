"""Add notification delivery kind.

Revision ID: 20260701_0023
Revises: 20260630_0022
Create Date: 2026-07-01
"""

import sqlalchemy as sa
from alembic import op

revision = "20260701_0023"
down_revision = "20260630_0022"
branch_labels = None
depends_on = None

DELIVERY_TABLE = "notification_email_deliveries"
DELIVERY_KIND_INDEX = "ix_notification_email_deliveries_delivery_kind"


def upgrade() -> None:
    if DELIVERY_TABLE not in _tables():
        return

    columns = _columns(DELIVERY_TABLE)
    if "delivery_kind" not in columns:
        with op.batch_alter_table(DELIVERY_TABLE) as batch_op:
            batch_op.add_column(sa.Column("delivery_kind", sa.String(length=16), nullable=True))

    op.execute(
        sa.text(
            """
            UPDATE notification_email_deliveries
            SET delivery_kind = CASE
                WHEN subject LIKE '%Recap%' THEN 'REPORT'
                ELSE 'ALERT'
            END
            WHERE delivery_kind IS NULL
            """
        )
    )

    if "delivery_kind" in _columns(DELIVERY_TABLE):
        with op.batch_alter_table(DELIVERY_TABLE) as batch_op:
            batch_op.alter_column("delivery_kind", existing_type=sa.String(length=16), nullable=False)

    if DELIVERY_KIND_INDEX not in _indexes(DELIVERY_TABLE):
        op.create_index(DELIVERY_KIND_INDEX, DELIVERY_TABLE, ["delivery_kind"])


def downgrade() -> None:
    if DELIVERY_TABLE not in _tables():
        return

    if DELIVERY_KIND_INDEX in _indexes(DELIVERY_TABLE):
        op.drop_index(DELIVERY_KIND_INDEX, table_name=DELIVERY_TABLE)

    if "delivery_kind" in _columns(DELIVERY_TABLE):
        with op.batch_alter_table(DELIVERY_TABLE) as batch_op:
            batch_op.drop_column("delivery_kind")


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def _indexes(table_name: str) -> set[str]:
    return {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table_name) if index["name"] is not None}
