"""Simplify notification delivery rows to final outbound emails.

Revision ID: 20260627_0018
Revises: 20260627_0017
Create Date: 2026-06-27
"""

import sqlalchemy as sa
from alembic import op

revision = "20260627_0018"
down_revision = "20260627_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "notification_email_deliveries" not in _tables():
        return

    columns = _columns("notification_email_deliveries")
    indexes = _indexes("notification_email_deliveries")
    unique_constraints = _unique_constraints("notification_email_deliveries")
    with op.batch_alter_table("notification_email_deliveries") as batch_op:
        if "uq_notification_email_deliveries_recipient_dedupe" in unique_constraints:
            batch_op.drop_constraint("uq_notification_email_deliveries_recipient_dedupe", type_="unique")
        for index_name in (
            "ix_notification_email_deliveries_notification_kind",
            "ix_notification_email_deliveries_delivery",
            "ix_notification_email_deliveries_dedupe_key",
        ):
            if index_name in indexes:
                batch_op.drop_index(index_name)
        for column_name in ("notification_kind", "delivery", "dedupe_key"):
            if column_name in columns:
                batch_op.drop_column(column_name)

    indexes = _indexes("notification_email_deliveries")
    if "idx_notification_email_deliveries_recipient_send" in indexes:
        op.drop_index("idx_notification_email_deliveries_recipient_send", table_name="notification_email_deliveries")
    _delete_duplicate_recipient_send_rows()
    with op.batch_alter_table("notification_email_deliveries") as batch_op:
        if "uq_notification_email_deliveries_recipient_send" not in _unique_constraints("notification_email_deliveries"):
            batch_op.create_unique_constraint(
                "uq_notification_email_deliveries_recipient_send",
                ["agency_id", "agency_email_id", "send_at"],
            )


def downgrade() -> None:
    if "notification_email_deliveries" not in _tables():
        return

    with op.batch_alter_table("notification_email_deliveries") as batch_op:
        if "uq_notification_email_deliveries_recipient_send" in _unique_constraints("notification_email_deliveries"):
            batch_op.drop_constraint("uq_notification_email_deliveries_recipient_send", type_="unique")

    if "idx_notification_email_deliveries_recipient_send" not in _indexes("notification_email_deliveries"):
        op.create_index(
            "idx_notification_email_deliveries_recipient_send",
            "notification_email_deliveries",
            ["agency_id", "agency_email_id", "send_at"],
        )

    columns = _columns("notification_email_deliveries")
    with op.batch_alter_table("notification_email_deliveries") as batch_op:
        if "notification_kind" not in columns:
            batch_op.add_column(sa.Column("notification_kind", sa.String(length=32), nullable=False, server_default="ALERTS"))
        if "delivery" not in columns:
            batch_op.add_column(sa.Column("delivery", sa.String(length=16), nullable=False, server_default="SCHEDULED"))
        if "dedupe_key" not in columns:
            batch_op.add_column(sa.Column("dedupe_key", sa.String(length=255), nullable=True))

    op.execute(sa.text("UPDATE notification_email_deliveries SET dedupe_key = 'LEGACY:' || id WHERE dedupe_key IS NULL"))

    indexes = _indexes("notification_email_deliveries")
    if "ix_notification_email_deliveries_notification_kind" not in indexes:
        op.create_index("ix_notification_email_deliveries_notification_kind", "notification_email_deliveries", ["notification_kind"])
    if "ix_notification_email_deliveries_delivery" not in indexes:
        op.create_index("ix_notification_email_deliveries_delivery", "notification_email_deliveries", ["delivery"])
    if "ix_notification_email_deliveries_dedupe_key" not in indexes:
        op.create_index("ix_notification_email_deliveries_dedupe_key", "notification_email_deliveries", ["dedupe_key"])
    with op.batch_alter_table("notification_email_deliveries") as batch_op:
        if "uq_notification_email_deliveries_recipient_dedupe" not in _unique_constraints("notification_email_deliveries"):
            batch_op.create_unique_constraint(
                "uq_notification_email_deliveries_recipient_dedupe",
                ["agency_id", "agency_email_id", "dedupe_key"],
            )


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


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


def _columns(table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def _indexes(table_name: str) -> set[str]:
    return {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table_name) if index["name"] is not None}


def _unique_constraints(table_name: str) -> set[str]:
    return {constraint["name"] for constraint in sa.inspect(op.get_bind()).get_unique_constraints(table_name) if constraint["name"] is not None}
