"""Add state-driven alert and notification delivery tables.

Revision ID: 20260626_0016
Revises: 20260624_0015
Create Date: 2026-06-26
"""

import sqlalchemy as sa
from alembic import op

revision = "20260626_0016"
down_revision = "20260624_0015"
branch_labels = None
depends_on = None

ALERT_TYPE = (
    "STOCKOUT",
    "STOCKOUT_FORECAST",
    "LOW_STOCK",
    "LOW_STOCK_FORECAST",
    "STALE_COUNT",
    "RARE_TAKEOUT",
    "UNKNOWN_UPC",
    "COUNT_ACTION",
    "RESTOCK_ACTION",
    "TAKEOUT_ACTION",
    "TRANSFER_ACTION",
)
ALERT_SEVERITY = ("INFO", "NOTICE", "WARNING", "HIGH", "CRITICAL")
ALERT_EVENT_STATUS = ("PENDING", "QUEUED", "NOTIFIED", "CANCELLED", "ERROR")
ALERT_SOURCE_TYPE = ("ACTION_LOG", "UNKNOWN_UPC_SCAN", "STALE_COUNT_AUDIT", "RARE_TAKEOUT_AUDIT")
EMAIL_STATUS = ("PENDING", "SENT", "ERROR", "CANCELLED")
NOTIFICATION_KIND = ("IMMEDIATE_ALERT", "HOURLY_DIGEST", "DAILY_DIGEST")


def upgrade() -> None:
    tables = _tables()
    if "inventory_balances" in tables and "inventory_storage_balances" not in tables:
        op.rename_table("inventory_balances", "inventory_storage_balances")

    tables = _tables()
    if "inventory_item_location_states" not in tables:
        _create_inventory_item_location_states()
        _backfill_item_location_states()

    if "inventory_alert_events" not in tables:
        _create_inventory_alert_events()

    if "notification_email_deliveries" not in tables:
        _create_notification_email_deliveries()

    tables = _tables()
    if "alert_records" in tables:
        op.drop_table("alert_records")
    if "inventory_trends" in tables:
        op.drop_table("inventory_trends")


def downgrade() -> None:
    tables = _tables()
    if "notification_email_deliveries" in tables:
        op.drop_table("notification_email_deliveries")
    if "inventory_alert_events" in tables:
        op.drop_table("inventory_alert_events")
    if "inventory_item_location_states" in tables:
        op.drop_table("inventory_item_location_states")
    if "inventory_storage_balances" in tables and "inventory_balances" not in tables:
        op.rename_table("inventory_storage_balances", "inventory_balances")


def _create_inventory_item_location_states() -> None:
    op.create_table(
        "inventory_item_location_states",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agency_id", sa.Integer(), sa.ForeignKey("agencies.id"), nullable=False),
        sa.Column("item_id", sa.Integer(), sa.ForeignKey("items.id"), nullable=False),
        sa.Column("agency_location_id", sa.Integer(), sa.ForeignKey("agency_locations.id"), nullable=False),
        sa.Column("total_quantity", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("min_quantity_snapshot", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lead_time_days_snapshot", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("restock_delivery_days_snapshot", sa.Integer(), nullable=True),
        sa.Column("last_counted_at", sa.DateTime(), nullable=True),
        sa.Column("last_activity_at", sa.DateTime(), nullable=True),
        sa.Column("last_takeout_at", sa.DateTime(), nullable=True),
        sa.Column("trend_per_day", sa.Float(), nullable=True),
        sa.Column("confidence_percent", sa.Float(), nullable=True),
        sa.Column("segment_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("data_signature", sa.String(length=64), nullable=True),
        sa.Column("trained_at", sa.DateTime(), nullable=True),
        sa.Column("days_until_low", sa.Float(), nullable=True),
        sa.Column("days_until_stockout", sa.Float(), nullable=True),
        sa.Column("stock_status", _enum(ALERT_TYPE, 32), nullable=True),
        sa.Column("forecast_status", _enum(ALERT_TYPE, 32), nullable=True),
        sa.Column("effective_alert_type", _enum(ALERT_TYPE, 32), nullable=True),
        sa.Column("effective_alert_rank", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("effective_severity", _enum(ALERT_SEVERITY, 16), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("state_version_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("agency_id", "item_id", "agency_location_id", name="uq_inventory_item_location_states_agency_item_location"),
    )
    op.create_index("ix_inventory_item_location_states_agency_id", "inventory_item_location_states", ["agency_id"])
    op.create_index("ix_inventory_item_location_states_item_id", "inventory_item_location_states", ["item_id"])
    op.create_index("ix_inventory_item_location_states_agency_location_id", "inventory_item_location_states", ["agency_location_id"])
    op.create_index(
        "idx_inventory_item_location_states_effective",
        "inventory_item_location_states",
        ["agency_id", "effective_alert_type", "effective_severity"],
    )
    op.create_index("idx_inventory_item_location_states_signature", "inventory_item_location_states", ["data_signature"])


def _create_inventory_alert_events() -> None:
    op.create_table(
        "inventory_alert_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agency_id", sa.Integer(), sa.ForeignKey("agencies.id"), nullable=False),
        sa.Column("alert_type", _enum(ALERT_TYPE, 32), nullable=False),
        sa.Column("severity", _enum(ALERT_SEVERITY, 16), nullable=False),
        sa.Column("status", _enum(ALERT_EVENT_STATUS, 16), nullable=False),
        sa.Column("source_type", _enum(ALERT_SOURCE_TYPE, 32), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.Column("dedupe_key", sa.String(length=255), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("event_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("queued_at", sa.DateTime(), nullable=True),
        sa.Column("notified_at", sa.DateTime(), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(), nullable=True),
        sa.Column("last_error_type", sa.String(length=100), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("last_error_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("agency_id", "dedupe_key", name="uq_inventory_alert_events_agency_dedupe_key"),
    )
    op.create_index("ix_inventory_alert_events_agency_id", "inventory_alert_events", ["agency_id"])
    op.create_index("ix_inventory_alert_events_alert_type", "inventory_alert_events", ["alert_type"])
    op.create_index("ix_inventory_alert_events_status", "inventory_alert_events", ["status"])
    op.create_index("idx_inventory_alert_events_agency_status_type", "inventory_alert_events", ["agency_id", "status", "alert_type"])


def _create_notification_email_deliveries() -> None:
    op.create_table(
        "notification_email_deliveries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agency_id", sa.Integer(), sa.ForeignKey("agencies.id"), nullable=False),
        sa.Column("agency_email_id", sa.Integer(), sa.ForeignKey("agency_emails.id"), nullable=False),
        sa.Column("recipient_email_snapshot", sa.String(length=255), nullable=False),
        sa.Column("notification_kind", _enum(NOTIFICATION_KIND, 32), nullable=False),
        sa.Column("status", _enum(EMAIL_STATUS, 16), nullable=False),
        sa.Column("send_at", sa.DateTime(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("dedupe_key", sa.String(length=255), nullable=False),
        sa.Column("alert_event_ids_json", sa.JSON(), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("preview_text", sa.String(length=255), nullable=False),
        sa.Column("body_html", sa.Text(), nullable=False),
        sa.Column("body_text", sa.Text(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error_type", sa.String(length=100), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("last_error_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("next_attempt_at IS NULL OR next_attempt_at >= send_at", name="ck_notification_email_next_attempt_after_send"),
        sa.UniqueConstraint("agency_id", "agency_email_id", "dedupe_key", name="uq_notification_email_deliveries_recipient_dedupe"),
    )
    op.create_index("ix_notification_email_deliveries_agency_id", "notification_email_deliveries", ["agency_id"])
    op.create_index("ix_notification_email_deliveries_agency_email_id", "notification_email_deliveries", ["agency_email_id"])
    op.create_index("idx_notification_email_deliveries_status_send", "notification_email_deliveries", ["status", "send_at"])


def _backfill_item_location_states() -> None:
    bind = op.get_bind()
    if "inventory_storage_balances" not in _tables():
        return
    trend_columns = _columns("inventory_trends") if "inventory_trends" in _tables() else set()
    has_trends = {"trend_per_day", "confidence_percent", "segment_count", "data_signature", "trained_at"}.issubset(trend_columns)
    trend_join = (
        """
        LEFT JOIN inventory_trends trends
          ON trends.agency_id = items.agency_id
         AND trends.item_id = items.id
         AND trends.agency_location_id = locations.id
    """
        if has_trends
        else ""
    )
    trend_select = (
        """
        MAX(trends.trend_per_day),
        MAX(trends.confidence_percent),
        COALESCE(MAX(trends.segment_count), 0),
        MAX(trends.data_signature),
        MAX(trends.trained_at),
    """
        if has_trends
        else """
        NULL,
        NULL,
        0,
        NULL,
        NULL,
    """
    )
    bind.execute(
        sa.text(
            f"""
            INSERT INTO inventory_item_location_states (
                agency_id,
                item_id,
                agency_location_id,
                total_quantity,
                min_quantity_snapshot,
                lead_time_days_snapshot,
                restock_delivery_days_snapshot,
                last_counted_at,
                last_activity_at,
                last_takeout_at,
                trend_per_day,
                confidence_percent,
                segment_count,
                data_signature,
                trained_at,
                stock_status,
                effective_alert_type,
                effective_alert_rank,
                effective_severity,
                state_version_at,
                updated_at
            )
            SELECT
                items.agency_id,
                items.id,
                locations.id,
                COALESCE(SUM(balances.quantity), 0),
                COALESCE(items.min_quantity, 0),
                COALESCE(items.restock_delivery_days, agencies.lead_time_days, 0),
                items.restock_delivery_days,
                MAX(balances.last_counted_at),
                MAX(balances.last_activity_at),
                MAX(balances.last_takeout_at),
                {trend_select}
                CASE
                    WHEN COALESCE(SUM(balances.quantity), 0) <= 0
                         AND MAX(balances.last_counted_at) IS NOT NULL THEN 'STOCKOUT'
                    WHEN COALESCE(SUM(balances.quantity), 0) < COALESCE(items.min_quantity, 0)
                         AND MAX(balances.last_counted_at) IS NOT NULL THEN 'LOW_STOCK'
                    ELSE NULL
                END,
                CASE
                    WHEN COALESCE(SUM(balances.quantity), 0) <= 0
                         AND MAX(balances.last_counted_at) IS NOT NULL THEN 'STOCKOUT'
                    WHEN COALESCE(SUM(balances.quantity), 0) < COALESCE(items.min_quantity, 0)
                         AND MAX(balances.last_counted_at) IS NOT NULL THEN 'LOW_STOCK'
                    ELSE NULL
                END,
                CASE
                    WHEN COALESCE(SUM(balances.quantity), 0) <= 0
                         AND MAX(balances.last_counted_at) IS NOT NULL THEN 400
                    WHEN COALESCE(SUM(balances.quantity), 0) < COALESCE(items.min_quantity, 0)
                         AND MAX(balances.last_counted_at) IS NOT NULL THEN 200
                    ELSE 0
                END,
                CASE
                    WHEN COALESCE(SUM(balances.quantity), 0) <= 0
                         AND MAX(balances.last_counted_at) IS NOT NULL THEN 'CRITICAL'
                    WHEN COALESCE(SUM(balances.quantity), 0) < COALESCE(items.min_quantity, 0)
                         AND MAX(balances.last_counted_at) IS NOT NULL THEN 'WARNING'
                    ELSE NULL
                END,
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP
            FROM items
            JOIN agencies ON agencies.id = items.agency_id
            JOIN agency_locations locations ON locations.agency_id = items.agency_id
            LEFT JOIN agency_storages storages ON storages.location_id = locations.id
            LEFT JOIN inventory_storage_balances balances
              ON balances.agency_id = items.agency_id
             AND balances.item_id = items.id
             AND balances.storage_id = storages.id
            {trend_join}
            WHERE items.active = 1 AND agencies.active = 1
            GROUP BY
                items.agency_id,
                items.id,
                locations.id,
                items.min_quantity,
                items.restock_delivery_days,
                agencies.lead_time_days
            """
        )
    )


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def _enum(values: tuple[str, ...], length: int) -> sa.Enum:
    return sa.Enum(*values, native_enum=False, length=length)
