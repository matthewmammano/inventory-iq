"""Mark undeliverable action events as no-recipient.

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

OLD_ALERT_EVENT_STATUS = ("PENDING", "QUEUED", "NOTIFIED", "CANCELLED", "ERROR")
NEW_ALERT_EVENT_STATUS = ("PENDING", "NO_RECIPIENT", "QUEUED", "NOTIFIED", "CANCELLED", "ERROR")
NO_RECIPIENT_EVENT_TYPES = (
    "COUNT_ACTION",
    "RESTOCK_ACTION",
    "TAKEOUT_ACTION",
    "TRANSFER_ACTION",
    "UNKNOWN_UPC",
    "STALE_COUNT",
    "RARE_TAKEOUT",
)


def upgrade() -> None:
    if "inventory_alert_events" not in _tables():
        return
    _alter_event_status_enum(OLD_ALERT_EVENT_STATUS, NEW_ALERT_EVENT_STATUS)
    if "agency_emails" not in _tables():
        return
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE inventory_alert_events AS events
            SET status = 'NO_RECIPIENT'
            WHERE events.status = 'PENDING'
              AND events.alert_type IN :event_types
              AND NOT EXISTS (
                  SELECT 1
                  FROM agency_emails recipients
                  WHERE recipients.agency_id = events.agency_id
                    AND recipients.active IS TRUE
                    AND CASE events.alert_type
                        WHEN 'COUNT_ACTION' THEN recipients.alert_for_count
                        WHEN 'RESTOCK_ACTION' THEN recipients.alert_for_restock
                        WHEN 'TAKEOUT_ACTION' THEN recipients.alert_for_takeout
                        WHEN 'TRANSFER_ACTION' THEN recipients.alert_for_transfer
                        WHEN 'UNKNOWN_UPC' THEN TRUE
                        WHEN 'STALE_COUNT' THEN recipients.alert_for_stale_count
                        WHEN 'RARE_TAKEOUT' THEN recipients.alert_for_rare_takeout
                        ELSE FALSE
                    END IS TRUE
              )
            """
        ).bindparams(sa.bindparam("event_types", expanding=True)),
        {"event_types": NO_RECIPIENT_EVENT_TYPES},
    )


def downgrade() -> None:
    if "inventory_alert_events" not in _tables():
        return
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE inventory_alert_events
            SET status = 'PENDING'
            WHERE status = 'NO_RECIPIENT'
            """
        )
    )
    _alter_event_status_enum(NEW_ALERT_EVENT_STATUS, OLD_ALERT_EVENT_STATUS)


def _alter_event_status_enum(existing_values: tuple[str, ...], new_values: tuple[str, ...]) -> None:
    with op.batch_alter_table("inventory_alert_events") as batch_op:
        batch_op.alter_column(
            "status",
            existing_type=_enum(existing_values, 16),
            type_=_enum(new_values, 16),
            existing_nullable=False,
        )


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _enum(values: tuple[str, ...], length: int) -> sa.Enum:
    return sa.Enum(*values, native_enum=False, length=length)
