"""Rebuild alerts as one table with a per-recipient ledger and an email audit.

Replaces `inventory_alert_events` + `recipient_alert_notifications` +
`notification_email_deliveries` with `alerts` (every notifiable problem, stock
or discrete; severity derived from type), `alert_notifications` (who was told,
about which alert, in which email), and `email_deliveries` (write-once send
audit). Stock alert state is no longer stored on item/location rows.

Revision ID: 20260708_0025
Revises: 20260706_0024
Create Date: 2026-07-08
"""

import sqlalchemy as sa
from alembic import op

revision = "20260708_0025"
down_revision = "20260706_0024"
branch_labels = None
depends_on = None

STATES = "inventory_item_location_states"
DROPPED_STATE_COLUMNS = (
    "stock_status",
    "forecast_status",
    "effective_alert_type",
    "effective_alert_rank",
    "effective_severity",
    "effective_alert_started_at",
)
DROPPED_STATE_INDEXES = (
    f"ix_{STATES}_stock_status",
    f"ix_{STATES}_forecast_status",
    f"ix_{STATES}_effective_alert_type",
    f"ix_{STATES}_effective_alert_rank",
    f"ix_{STATES}_effective_severity",
    f"idx_{STATES}_effective",
)
OLD_TABLES = ("recipient_alert_notifications", "notification_email_deliveries", "inventory_alert_events")


def upgrade() -> None:
    for table_name in OLD_TABLES:
        if table_name in _tables():
            op.drop_table(table_name)
    _drop_state_alert_columns()
    _create_alerts()
    _create_email_deliveries()
    _create_alert_notifications()


def downgrade() -> None:
    for table_name in ("alert_notifications", "email_deliveries", "alerts"):
        if table_name in _tables():
            op.drop_table(table_name)
    _restore_state_alert_columns()
    _recreate_inventory_alert_events()
    _recreate_notification_email_deliveries()


# --------------------------------------------------------------------------- #
# New schema
# --------------------------------------------------------------------------- #


def _create_alerts() -> None:
    op.create_table(
        "alerts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agency_id", sa.Integer(), sa.ForeignKey("agencies.id"), nullable=False),
        sa.Column("alert_type", sa.String(length=32), nullable=False),
        sa.Column("item_id", sa.Integer(), sa.ForeignKey("items.id"), nullable=True),
        sa.Column("agency_location_id", sa.Integer(), sa.ForeignKey("agency_locations.id"), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("closed_reason", sa.String(length=16), nullable=True),
        sa.Column("dedupe_key", sa.String(length=255), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=False),
        sa.Column("opened_at", sa.DateTime(), nullable=False),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
    )
    for column_name in ("agency_id", "alert_type", "item_id", "agency_location_id", "status", "dedupe_key", "opened_at"):
        op.create_index(f"ix_alerts_{column_name}", "alerts", [column_name])
    op.create_index("idx_alerts_agency_status_type", "alerts", ["agency_id", "status", "alert_type"])
    op.create_index(
        "uq_alerts_open_dedupe_key",
        "alerts",
        ["agency_id", "dedupe_key"],
        unique=True,
        postgresql_where=sa.text("status = 'OPEN'"),
        sqlite_where=sa.text("status = 'OPEN'"),
    )


def _create_email_deliveries() -> None:
    op.create_table(
        "email_deliveries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agency_id", sa.Integer(), sa.ForeignKey("agencies.id"), nullable=False),
        sa.Column("notification_recipient_id", sa.Integer(), sa.ForeignKey("notification_recipients.id"), nullable=False),
        sa.Column("recipient_email_snapshot", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=True),
        sa.Column("preview_text", sa.String(length=255), nullable=True),
        sa.Column("error_type", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
    )
    for column_name in ("agency_id", "notification_recipient_id", "kind", "status", "created_at", "sent_at"):
        op.create_index(f"ix_email_deliveries_{column_name}", "email_deliveries", [column_name])
    op.create_index("idx_email_deliveries_recipient_kind_sent", "email_deliveries", ["notification_recipient_id", "kind", "sent_at"])


def _create_alert_notifications() -> None:
    op.create_table(
        "alert_notifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("alert_id", sa.Integer(), sa.ForeignKey("alerts.id"), nullable=False),
        sa.Column("notification_recipient_id", sa.Integer(), sa.ForeignKey("notification_recipients.id"), nullable=False),
        sa.Column("email_delivery_id", sa.Integer(), sa.ForeignKey("email_deliveries.id"), nullable=False),
        sa.Column("notified_at", sa.DateTime(), nullable=False),
    )
    for column_name in ("alert_id", "notification_recipient_id", "email_delivery_id"):
        op.create_index(f"ix_alert_notifications_{column_name}", "alert_notifications", [column_name])
    op.create_index("idx_alert_notifications_recipient_alert", "alert_notifications", ["notification_recipient_id", "alert_id", "notified_at"])


def _drop_state_alert_columns() -> None:
    columns = _columns(STATES)
    indexes = _indexes(STATES)
    for index_name in DROPPED_STATE_INDEXES:
        if index_name in indexes:
            op.drop_index(index_name, table_name=STATES)
    with op.batch_alter_table(STATES) as batch_op:
        for column_name in DROPPED_STATE_COLUMNS:
            if column_name in columns:
                batch_op.drop_column(column_name)


# --------------------------------------------------------------------------- #
# Downgrade: restore the pre-0025 shape
# --------------------------------------------------------------------------- #


def _restore_state_alert_columns() -> None:
    columns = _columns(STATES)
    with op.batch_alter_table(STATES) as batch_op:
        for column_name in ("stock_status", "forecast_status", "effective_alert_type", "effective_severity"):
            if column_name not in columns:
                batch_op.add_column(sa.Column(column_name, sa.String(length=32), nullable=True))
        if "effective_alert_rank" not in columns:
            batch_op.add_column(sa.Column("effective_alert_rank", sa.Integer(), nullable=False, server_default="0"))
        if "effective_alert_started_at" not in columns:
            batch_op.add_column(sa.Column("effective_alert_started_at", sa.DateTime(), nullable=True))
    for column_name in ("stock_status", "forecast_status", "effective_alert_type", "effective_alert_rank", "effective_severity"):
        index_name = f"ix_{STATES}_{column_name}"
        if index_name not in _indexes(STATES):
            op.create_index(index_name, STATES, [column_name])
    if f"idx_{STATES}_effective" not in _indexes(STATES):
        op.create_index(f"idx_{STATES}_effective", STATES, ["agency_id", "effective_alert_type", "effective_severity"])


def _recreate_inventory_alert_events() -> None:
    if "inventory_alert_events" in _tables():
        return
    op.create_table(
        "inventory_alert_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agency_id", sa.Integer(), sa.ForeignKey("agencies.id"), nullable=False),
        sa.Column("alert_type", sa.String(length=32), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.Column("dedupe_key", sa.String(length=255), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("event_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("queued_at", sa.DateTime(), nullable=True),
        sa.Column("notified_at", sa.DateTime(), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(), nullable=True),
        sa.Column("last_error_type", sa.String(length=100), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("last_error_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("agency_id", "dedupe_key", name="uq_inventory_alert_events_agency_dedupe_key"),
    )
    for column_name in ("agency_id", "alert_type", "severity", "status", "source_type", "source_id", "dedupe_key", "event_at", "created_at"):
        op.create_index(f"ix_inventory_alert_events_{column_name}", "inventory_alert_events", [column_name])
    op.create_index("idx_inventory_alert_events_agency_status_type", "inventory_alert_events", ["agency_id", "status", "alert_type"])


def _recreate_notification_email_deliveries() -> None:
    if "notification_email_deliveries" in _tables():
        return
    op.create_table(
        "notification_email_deliveries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agency_id", sa.Integer(), sa.ForeignKey("agencies.id"), nullable=False),
        sa.Column("notification_recipient_id", sa.Integer(), sa.ForeignKey("notification_recipients.id"), nullable=False),
        sa.Column("recipient_email_snapshot", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("delivery_kind", sa.String(length=16), nullable=False),
        sa.Column("send_at", sa.DateTime(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("subject", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("preview_text", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("body_html", sa.Text(), nullable=False, server_default=""),
        sa.Column("body_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error_type", sa.String(length=100), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("last_error_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("state_alert_keys_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("alert_event_ids_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("delivery_key", sa.String(length=255), nullable=False, server_default=""),
        sa.UniqueConstraint("agency_id", "notification_recipient_id", "delivery_key", name="uq_notification_email_deliveries_recipient_key"),
    )
    for column_name in ("agency_id", "notification_recipient_id", "status", "delivery_kind", "send_at", "next_attempt_at", "created_at", "sent_at"):
        op.create_index(f"ix_notification_email_deliveries_{column_name}", "notification_email_deliveries", [column_name])
    op.create_index("ix_notification_email_deliveries_delivery_key", "notification_email_deliveries", ["delivery_key"])
    op.create_index("idx_notification_email_deliveries_status_send", "notification_email_deliveries", ["status", "send_at"])


# --------------------------------------------------------------------------- #
# Introspection helpers
# --------------------------------------------------------------------------- #


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def _indexes(table_name: str) -> set[str]:
    return {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table_name) if index["name"] is not None}
