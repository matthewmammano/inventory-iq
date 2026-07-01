"""Use delivery keys instead of unique recipient/send_at pairs.

Revision ID: 20260630_0022
Revises: 20260629_0021
Create Date: 2026-06-30
"""

import sqlalchemy as sa
from alembic import op

revision = "20260630_0022"
down_revision = "20260629_0021"
branch_labels = None
depends_on = None

DELIVERY_TABLE = "notification_email_deliveries"
RECIPIENT_SEND_CONSTRAINT = "uq_notification_email_deliveries_recipient_send"
RECIPIENT_KEY_CONSTRAINT = "uq_notification_email_deliveries_recipient_key"
DELIVERY_KEY_INDEX = "ix_notification_email_deliveries_delivery_key"


def upgrade() -> None:
    if DELIVERY_TABLE not in _tables():
        return

    columns = _columns(DELIVERY_TABLE)
    unique_constraints = _unique_constraints(DELIVERY_TABLE)
    indexes = _indexes(DELIVERY_TABLE)

    with op.batch_alter_table(DELIVERY_TABLE) as batch_op:
        if RECIPIENT_SEND_CONSTRAINT in unique_constraints:
            batch_op.drop_constraint(RECIPIENT_SEND_CONSTRAINT, type_="unique")
        if "delivery_key" not in columns:
            batch_op.add_column(sa.Column("delivery_key", sa.String(length=255), nullable=True))

    op.execute(sa.text("UPDATE notification_email_deliveries SET delivery_key = 'LEGACY:' || id WHERE delivery_key IS NULL"))

    with op.batch_alter_table(DELIVERY_TABLE) as batch_op:
        if RECIPIENT_KEY_CONSTRAINT not in _unique_constraints(DELIVERY_TABLE):
            batch_op.create_unique_constraint(
                RECIPIENT_KEY_CONSTRAINT,
                ["agency_id", "agency_email_id", "delivery_key"],
            )
        if "delivery_key" in _columns(DELIVERY_TABLE):
            batch_op.alter_column("delivery_key", existing_type=sa.String(length=255), nullable=False)

    if DELIVERY_KEY_INDEX not in indexes and DELIVERY_KEY_INDEX not in _indexes(DELIVERY_TABLE):
        op.create_index(DELIVERY_KEY_INDEX, DELIVERY_TABLE, ["delivery_key"])


def downgrade() -> None:
    if DELIVERY_TABLE not in _tables():
        return

    _delete_duplicate_recipient_send_rows()
    unique_constraints = _unique_constraints(DELIVERY_TABLE)
    indexes = _indexes(DELIVERY_TABLE)
    columns = _columns(DELIVERY_TABLE)

    if DELIVERY_KEY_INDEX in indexes:
        op.drop_index(DELIVERY_KEY_INDEX, table_name=DELIVERY_TABLE)

    with op.batch_alter_table(DELIVERY_TABLE) as batch_op:
        if RECIPIENT_KEY_CONSTRAINT in unique_constraints:
            batch_op.drop_constraint(RECIPIENT_KEY_CONSTRAINT, type_="unique")
        if RECIPIENT_SEND_CONSTRAINT not in _unique_constraints(DELIVERY_TABLE):
            batch_op.create_unique_constraint(
                RECIPIENT_SEND_CONSTRAINT,
                ["agency_id", "agency_email_id", "send_at"],
            )
        if "delivery_key" in columns:
            batch_op.drop_column("delivery_key")


def _delete_duplicate_recipient_send_rows() -> None:
    op.execute(
        sa.text(
            """
            WITH ranked AS (
                SELECT
                    id,
                    ROW_NUMBER() OVER (
                        PARTITION BY agency_id, agency_email_id, send_at
                        ORDER BY id DESC
                    ) AS row_num
                FROM notification_email_deliveries
            )
            DELETE FROM notification_email_deliveries
            WHERE id IN (
                SELECT id
                FROM ranked
                WHERE row_num > 1
            )
            """
        )
    )


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def _indexes(table_name: str) -> set[str]:
    return {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table_name) if index["name"] is not None}


def _unique_constraints(table_name: str) -> set[str]:
    return {constraint["name"] for constraint in sa.inspect(op.get_bind()).get_unique_constraints(table_name) if constraint["name"] is not None}
