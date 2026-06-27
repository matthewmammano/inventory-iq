"""Split notification content kind from delivery timing.

Revision ID: 20260627_0017
Revises: 20260626_0016
Create Date: 2026-06-27
"""

import sqlalchemy as sa
from alembic import op

revision = "20260627_0017"
down_revision = "20260626_0016"
branch_labels = None
depends_on = None

NOTIFICATION_DELIVERY = ("IMMEDIATE", "SCHEDULED")


def upgrade() -> None:
    if "notification_email_deliveries" not in _tables():
        return

    columns = _columns("notification_email_deliveries")
    if "delivery" not in columns:
        op.add_column(
            "notification_email_deliveries",
            sa.Column(
                "delivery",
                sa.Enum(*NOTIFICATION_DELIVERY, native_enum=False, length=16),
                nullable=False,
                server_default="SCHEDULED",
            ),
        )
        if op.get_bind().dialect.name != "sqlite":
            op.alter_column("notification_email_deliveries", "delivery", server_default=None)

    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE notification_email_deliveries
               SET delivery = CASE
                       WHEN notification_kind = 'IMMEDIATE_ALERT' THEN 'IMMEDIATE'
                       ELSE 'SCHEDULED'
                   END,
                   notification_kind = CASE
                       WHEN notification_kind = 'DAILY_DIGEST' THEN 'RECAPS'
                       ELSE 'ALERTS'
                   END
             WHERE notification_kind IN ('IMMEDIATE_ALERT', 'HOURLY_DIGEST', 'DAILY_DIGEST')
            """
        )
    )

    indexes = _indexes("notification_email_deliveries")
    if "ix_notification_email_deliveries_delivery" not in indexes:
        op.create_index("ix_notification_email_deliveries_delivery", "notification_email_deliveries", ["delivery"])


def downgrade() -> None:
    if "notification_email_deliveries" not in _tables():
        return

    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE notification_email_deliveries
               SET notification_kind = CASE
                       WHEN notification_kind = 'RECAPS' THEN 'DAILY_DIGEST'
                       WHEN delivery = 'IMMEDIATE' THEN 'IMMEDIATE_ALERT'
                       ELSE 'HOURLY_DIGEST'
                   END
             WHERE notification_kind IN ('ALERTS', 'RECAPS')
            """
        )
    )

    if "ix_notification_email_deliveries_delivery" in _indexes("notification_email_deliveries"):
        op.drop_index("ix_notification_email_deliveries_delivery", table_name="notification_email_deliveries")
    if "delivery" in _columns("notification_email_deliveries"):
        op.drop_column("notification_email_deliveries", "delivery")


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def _indexes(table_name: str) -> set[str]:
    return {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table_name) if index["name"] is not None}
