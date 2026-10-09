"""Full schema baseline. Squashes the v1 incremental history into one frozen snapshot.

Revision ID: 20261008_0001
Revises: None
Create Date: 2026-10-08
"""

import sqlalchemy as sa
from alembic import op

revision = "20261008_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agencies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("display_name", sa.String(length=50), nullable=False),
        sa.Column("email", sa.String(length=128), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("image", sa.Text(), nullable=True),
        sa.Column("timezone", sa.String(length=50), nullable=False),
        sa.Column("password", sa.Text(), nullable=True),
        sa.Column("pin", sa.Text(), nullable=False),
        sa.Column("user_count_allow", sa.Boolean(), nullable=False),
        sa.Column("user_restock_allow", sa.Boolean(), nullable=False),
        sa.Column("lead_time_days", sa.Integer(), nullable=False),
        sa.Column("count_last_days", sa.Integer(), nullable=False),
        sa.Column("alert_rare_scan_days", sa.Integer(), nullable=False),
        sa.Column("expiration_notice_days", sa.Integer(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("display_name"),
        sa.UniqueConstraint("email"),
    )
    op.create_table(
        "scheduler_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("agency_id", sa.Integer(), nullable=False),
        sa.Column("job_name", sa.String(length=80), nullable=False),
        sa.Column("period_key", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_name", "agency_id", "period_key", name="uq_scheduler_runs_job_agency_period"),
    )
    op.create_index(op.f("ix_scheduler_runs_agency_id"), "scheduler_runs", ["agency_id"], unique=False)
    op.create_index(op.f("ix_scheduler_runs_job_name"), "scheduler_runs", ["job_name"], unique=False)
    op.create_index(op.f("ix_scheduler_runs_period_key"), "scheduler_runs", ["period_key"], unique=False)
    op.create_index(op.f("ix_scheduler_runs_status"), "scheduler_runs", ["status"], unique=False)
    op.create_table(
        "agency_item_tags",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("agency_id", sa.Integer(), nullable=False),
        sa.Column("tag_name", sa.String(length=50), nullable=False),
        sa.Column("color", sa.String(length=7), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["agency_id"],
            ["agencies.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agency_id", "tag_name", name="uq_agency_item_tags_agency_tag"),
    )
    op.create_index(op.f("ix_agency_item_tags_agency_id"), "agency_item_tags", ["agency_id"], unique=False)
    op.create_table(
        "agency_locations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("agency_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.ForeignKeyConstraint(
            ["agency_id"],
            ["agencies.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agency_id", "name", name="uq_agency_locations_agency_name"),
    )
    op.create_index(op.f("ix_agency_locations_agency_id"), "agency_locations", ["agency_id"], unique=False)
    op.create_table(
        "items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("agency_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("upc", sa.String(length=12), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("guest_quick_adjust", sa.Boolean(), nullable=False),
        sa.Column("increments", sa.String(length=50), nullable=True),
        sa.Column("tag_ids", sa.JSON(), nullable=False),
        sa.Column("image", sa.String(length=1024), nullable=True),
        sa.Column("expiration_tracking_enabled", sa.Boolean(), nullable=False),
        sa.Column("expiration_notice_days_override", sa.Integer(), nullable=True),
        sa.Column("scan_alert_flagged", sa.Boolean(), nullable=False),
        sa.Column("min_quantity", sa.Integer(), nullable=False),
        sa.Column("max_quantity", sa.Integer(), nullable=False),
        sa.Column("batch_size", sa.Integer(), nullable=True),
        sa.Column("restock_delivery_days", sa.Integer(), nullable=True),
        sa.Column("prior_daily_usage", sa.Float(), nullable=True),
        sa.Column("last_accessed", sa.DateTime(), nullable=True),
        sa.CheckConstraint("upc LIKE '042%'", name="ck_items_upc_private_prefix"),
        sa.ForeignKeyConstraint(
            ["agency_id"],
            ["agencies.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agency_id", "upc", name="uq_items_agency_upc"),
    )
    op.create_index("idx_agency_last_accessed", "items", ["agency_id", "last_accessed"], unique=False)
    op.create_index("idx_agency_name", "items", ["agency_id", "name"], unique=False)
    op.create_index("idx_agency_upc", "items", ["agency_id", "upc"], unique=False)
    op.create_table(
        "notification_recipients",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("agency_id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=128), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("location_filter_ids", sa.JSON(), nullable=True),
        sa.Column("quiet_start_time", sa.String(length=5), nullable=True),
        sa.Column("quiet_end_time", sa.String(length=5), nullable=True),
        sa.Column("alert_frequency", sa.Enum("INSTANT", "HOURLY", "DAILY", name="alertemailfrequency", native_enum=False, length=16), nullable=False),
        sa.Column("scan_alert_scope", sa.Enum("ALL", "FLAGGED", name="scanalertscope", native_enum=False, length=16), nullable=False),
        sa.CheckConstraint(
            "(quiet_start_time IS NULL AND quiet_end_time IS NULL) OR (quiet_start_time IS NOT NULL AND quiet_end_time IS NOT NULL)",
            name="ck_notification_recipients_quiet_hours_pair",
        ),
        sa.ForeignKeyConstraint(
            ["agency_id"],
            ["agencies.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agency_id", "email", name="uq_notification_recipients_agency_email"),
    )
    op.create_index(op.f("ix_notification_recipients_agency_id"), "notification_recipients", ["agency_id"], unique=False)
    op.create_table(
        "password_reset_pins",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("agency_id", sa.Integer(), nullable=False),
        sa.Column("pin_hash", sa.String(length=255), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["agency_id"],
            ["agencies.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_password_reset_pins_agency_id"), "password_reset_pins", ["agency_id"], unique=False)
    op.create_index(op.f("ix_password_reset_pins_expires_at"), "password_reset_pins", ["expires_at"], unique=False)
    op.create_table(
        "agency_devices",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("agency_id", sa.Integer(), nullable=False),
        sa.Column("agency_location_id", sa.Integer(), nullable=True),
        sa.Column("device_token_hash", sa.String(length=64), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["agency_id"],
            ["agencies.id"],
        ),
        sa.ForeignKeyConstraint(
            ["agency_location_id"],
            ["agency_locations.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_agency_devices_agency_id"), "agency_devices", ["agency_id"], unique=False)
    op.create_index(op.f("ix_agency_devices_device_token_hash"), "agency_devices", ["device_token_hash"], unique=True)
    op.create_table(
        "agency_storages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("agency_id", sa.Integer(), nullable=False),
        sa.Column("location_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("user_access_from", sa.Boolean(), nullable=False),
        sa.Column("user_access_to", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["agency_id"],
            ["agencies.id"],
        ),
        sa.ForeignKeyConstraint(
            ["location_id"],
            ["agency_locations.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("location_id", "name", name="uq_agency_storages_location_name"),
    )
    op.create_index(op.f("ix_agency_storages_agency_id"), "agency_storages", ["agency_id"], unique=False)
    op.create_index(op.f("ix_agency_storages_location_id"), "agency_storages", ["location_id"], unique=False)
    op.create_table(
        "alerts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("agency_id", sa.Integer(), nullable=False),
        sa.Column(
            "alert_type",
            sa.Enum(
                "STOCKOUT",
                "STOCKOUT_FORECAST",
                "LOW_STOCK",
                "LOW_STOCK_FORECAST",
                "STALE_COUNT",
                "RARE_TAKEOUT",
                "COUNT_ACTION",
                "RESTOCK_ACTION",
                "TAKEOUT_ACTION",
                "TRANSFER_ACTION",
                "UNKNOWN_UPC",
                "EXPIRED_STOCK",
                "EXPIRING_SOON",
                "EXPIRATION_COUNT_NEEDED",
                name="alerttype",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("item_id", sa.Integer(), nullable=True),
        sa.Column("agency_location_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.Enum("OPEN", "CLOSED", name="alertstatus", native_enum=False, length=16), nullable=False),
        sa.Column("closed_reason", sa.Enum("RESOLVED", "SUPERSEDED", "SENT", name="closedreason", native_enum=False, length=16), nullable=True),
        sa.Column("dedupe_key", sa.String(length=255), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=False),
        sa.Column("opened_at", sa.DateTime(), nullable=False),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["agency_id"],
            ["agencies.id"],
        ),
        sa.ForeignKeyConstraint(
            ["agency_location_id"],
            ["agency_locations.id"],
        ),
        sa.ForeignKeyConstraint(
            ["item_id"],
            ["items.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_alerts_agency_status_type", "alerts", ["agency_id", "status", "alert_type"], unique=False)
    op.create_index(op.f("ix_alerts_agency_id"), "alerts", ["agency_id"], unique=False)
    op.create_index(op.f("ix_alerts_agency_location_id"), "alerts", ["agency_location_id"], unique=False)
    op.create_index(op.f("ix_alerts_alert_type"), "alerts", ["alert_type"], unique=False)
    op.create_index(op.f("ix_alerts_dedupe_key"), "alerts", ["dedupe_key"], unique=False)
    op.create_index(op.f("ix_alerts_item_id"), "alerts", ["item_id"], unique=False)
    op.create_index(op.f("ix_alerts_opened_at"), "alerts", ["opened_at"], unique=False)
    op.create_index(op.f("ix_alerts_status"), "alerts", ["status"], unique=False)
    op.create_index(
        "uq_alerts_open_dedupe_key",
        "alerts",
        ["agency_id", "dedupe_key"],
        unique=True,
        postgresql_where=sa.text("status = 'OPEN'"),
        sqlite_where=sa.text("status = 'OPEN'"),
    )
    op.create_table(
        "email_deliveries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("agency_id", sa.Integer(), nullable=False),
        sa.Column("notification_recipient_id", sa.Integer(), nullable=False),
        sa.Column("recipient_email_snapshot", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.Enum("ALERT", "REPORT", name="notificationdeliverykind", native_enum=False, length=16), nullable=False),
        sa.Column("status", sa.Enum("SENT", "ERROR", name="deliverystatus", native_enum=False, length=16), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=True),
        sa.Column("preview_text", sa.String(length=255), nullable=True),
        sa.Column("error_type", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["agency_id"],
            ["agencies.id"],
        ),
        sa.ForeignKeyConstraint(
            ["notification_recipient_id"],
            ["notification_recipients.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_email_deliveries_recipient_kind_sent", "email_deliveries", ["notification_recipient_id", "kind", "sent_at"], unique=False)
    op.create_index(op.f("ix_email_deliveries_agency_id"), "email_deliveries", ["agency_id"], unique=False)
    op.create_index(op.f("ix_email_deliveries_created_at"), "email_deliveries", ["created_at"], unique=False)
    op.create_index(op.f("ix_email_deliveries_kind"), "email_deliveries", ["kind"], unique=False)
    op.create_index(op.f("ix_email_deliveries_notification_recipient_id"), "email_deliveries", ["notification_recipient_id"], unique=False)
    op.create_index(op.f("ix_email_deliveries_sent_at"), "email_deliveries", ["sent_at"], unique=False)
    op.create_index(op.f("ix_email_deliveries_status"), "email_deliveries", ["status"], unique=False)
    op.create_table(
        "inventory_item_location_states",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("agency_id", sa.Integer(), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("agency_location_id", sa.Integer(), nullable=False),
        sa.Column("total_quantity", sa.Integer(), nullable=False),
        sa.Column("min_quantity_snapshot", sa.Integer(), nullable=False),
        sa.Column("lead_time_days_snapshot", sa.Integer(), nullable=False),
        sa.Column("restock_delivery_days_snapshot", sa.Integer(), nullable=True),
        sa.Column("last_counted_at", sa.DateTime(), nullable=True),
        sa.Column("last_activity_at", sa.DateTime(), nullable=True),
        sa.Column("last_takeout_at", sa.DateTime(), nullable=True),
        sa.Column("trend_per_day", sa.Float(), nullable=True),
        sa.Column("confidence_percent", sa.Float(), nullable=True),
        sa.Column("segment_count", sa.Integer(), nullable=False),
        sa.Column("data_signature", sa.String(length=64), nullable=True),
        sa.Column("trained_at", sa.DateTime(), nullable=True),
        sa.Column("days_until_low", sa.Float(), nullable=True),
        sa.Column("days_until_stockout", sa.Float(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("state_version_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["agency_id"],
            ["agencies.id"],
        ),
        sa.ForeignKeyConstraint(
            ["agency_location_id"],
            ["agency_locations.id"],
        ),
        sa.ForeignKeyConstraint(
            ["item_id"],
            ["items.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agency_id", "item_id", "agency_location_id", name="uq_inventory_item_location_states_agency_item_location"),
    )
    op.create_index("idx_inventory_item_location_states_signature", "inventory_item_location_states", ["data_signature"], unique=False)
    op.create_index(op.f("ix_inventory_item_location_states_agency_id"), "inventory_item_location_states", ["agency_id"], unique=False)
    op.create_index(
        op.f("ix_inventory_item_location_states_agency_location_id"), "inventory_item_location_states", ["agency_location_id"], unique=False
    )
    op.create_index(op.f("ix_inventory_item_location_states_item_id"), "inventory_item_location_states", ["item_id"], unique=False)
    op.create_index(op.f("ix_inventory_item_location_states_state_version_at"), "inventory_item_location_states", ["state_version_at"], unique=False)
    op.create_table(
        "item_secondary_upcs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("agency_id", sa.Integer(), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("upc", sa.String(length=12), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.CheckConstraint("upc NOT LIKE '042%'", name="ck_item_secondary_upcs_not_private_prefix"),
        sa.ForeignKeyConstraint(
            ["agency_id"],
            ["agencies.id"],
        ),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agency_id", "upc", name="uq_item_secondary_upcs_agency_upc"),
    )
    op.create_index("idx_item_secondary_upcs_agency_item", "item_secondary_upcs", ["agency_id", "item_id"], unique=False)
    op.create_index("idx_item_secondary_upcs_agency_upc", "item_secondary_upcs", ["agency_id", "upc"], unique=False)
    op.create_index(op.f("ix_item_secondary_upcs_agency_id"), "item_secondary_upcs", ["agency_id"], unique=False)
    op.create_index(op.f("ix_item_secondary_upcs_item_id"), "item_secondary_upcs", ["item_id"], unique=False)
    op.create_table(
        "notification_preferences",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("recipient_id", sa.Integer(), nullable=False),
        sa.Column(
            "preference_key",
            sa.Enum(
                "STOCKOUT",
                "STOCKOUT_FORECAST",
                "LOW_STOCK",
                "LOW_STOCK_FORECAST",
                "STALE_COUNT",
                "RARE_TAKEOUT",
                "COUNT_ACTION",
                "RESTOCK_ACTION",
                "TAKEOUT_ACTION",
                "TRANSFER_ACTION",
                "UNKNOWN_UPC",
                "EXPIRED_STOCK",
                "EXPIRING_SOON",
                "EXPIRATION_COUNT_NEEDED",
                "DAILY_SUMMARY",
                "WEEKLY_SUMMARY",
                "MONTHLY_SUMMARY",
                "YEARLY_SUMMARY",
                name="notificationpreferencekey",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["recipient_id"], ["notification_recipients.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("recipient_id", "preference_key", name="uq_notification_preferences_recipient_key"),
    )
    op.create_index(op.f("ix_notification_preferences_preference_key"), "notification_preferences", ["preference_key"], unique=False)
    op.create_index(op.f("ix_notification_preferences_recipient_id"), "notification_preferences", ["recipient_id"], unique=False)
    op.create_table(
        "unknown_upc_scans",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("agency_id", sa.Integer(), nullable=False),
        sa.Column("upc", sa.String(length=12), nullable=False),
        sa.Column("status", sa.Enum("PENDING", "RESOLVED", "IGNORE", name="unknownupcstatus"), nullable=False),
        sa.Column("suggested_item_id", sa.Integer(), nullable=True),
        sa.Column("lookup_title", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["agency_id"],
            ["agencies.id"],
        ),
        sa.ForeignKeyConstraint(
            ["suggested_item_id"],
            ["items.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agency_id", "upc", name="uq_unknown_upc_scans_agency_upc"),
    )
    op.create_index("idx_unknown_upc_scans_agency_status_created", "unknown_upc_scans", ["agency_id", "status", "created_at"], unique=False)
    op.create_index(op.f("ix_unknown_upc_scans_agency_id"), "unknown_upc_scans", ["agency_id"], unique=False)
    op.create_index(op.f("ix_unknown_upc_scans_created_at"), "unknown_upc_scans", ["created_at"], unique=False)
    op.create_index(op.f("ix_unknown_upc_scans_status"), "unknown_upc_scans", ["status"], unique=False)
    op.create_table(
        "action_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("agency_id", sa.Integer(), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=True),
        sa.Column("operation_type", sa.Enum("COUNT", "RESTOCK", "TAKEOUT", "TRANSFER", name="operationtype"), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("from_storage_id", sa.Integer(), nullable=True),
        sa.Column("to_storage_id", sa.Integer(), nullable=True),
        sa.Column("admin_action", sa.Boolean(), nullable=False),
        sa.Column("time_scanned", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["agency_id"],
            ["agencies.id"],
        ),
        sa.ForeignKeyConstraint(
            ["from_storage_id"],
            ["agency_storages.id"],
        ),
        sa.ForeignKeyConstraint(
            ["item_id"],
            ["items.id"],
        ),
        sa.ForeignKeyConstraint(
            ["to_storage_id"],
            ["agency_storages.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_action_logs_agency_from_operation_time_id",
        "action_logs",
        ["agency_id", "from_storage_id", "operation_type", "time_scanned", "id"],
        unique=False,
    )
    op.create_index("idx_action_logs_agency_id_desc", "action_logs", ["agency_id", "id"], unique=False)
    op.create_index("idx_action_logs_agency_item_time_id", "action_logs", ["agency_id", "item_id", "time_scanned", "id"], unique=False)
    op.create_index(
        "idx_action_logs_agency_to_operation_time_id",
        "action_logs",
        ["agency_id", "to_storage_id", "operation_type", "time_scanned", "id"],
        unique=False,
    )
    op.create_index("idx_agency_from_location", "action_logs", ["agency_id", "from_storage_id"], unique=False)
    op.create_index("idx_agency_item_id", "action_logs", ["agency_id", "item_id"], unique=False)
    op.create_index("idx_agency_to_location", "action_logs", ["agency_id", "to_storage_id"], unique=False)
    op.create_table(
        "alert_notifications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("alert_id", sa.Integer(), nullable=False),
        sa.Column("notification_recipient_id", sa.Integer(), nullable=False),
        sa.Column("email_delivery_id", sa.Integer(), nullable=False),
        sa.Column("notified_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["alert_id"],
            ["alerts.id"],
        ),
        sa.ForeignKeyConstraint(
            ["email_delivery_id"],
            ["email_deliveries.id"],
        ),
        sa.ForeignKeyConstraint(
            ["notification_recipient_id"],
            ["notification_recipients.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_alert_notifications_recipient_alert", "alert_notifications", ["notification_recipient_id", "alert_id", "notified_at"], unique=False
    )
    op.create_index(op.f("ix_alert_notifications_alert_id"), "alert_notifications", ["alert_id"], unique=False)
    op.create_index(op.f("ix_alert_notifications_email_delivery_id"), "alert_notifications", ["email_delivery_id"], unique=False)
    op.create_index(op.f("ix_alert_notifications_notification_recipient_id"), "alert_notifications", ["notification_recipient_id"], unique=False)
    op.create_table(
        "inventory_expiration_balances",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("agency_id", sa.Integer(), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("storage_id", sa.Integer(), nullable=False),
        sa.Column("expires_on", sa.Date(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("last_counted_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["agency_id"],
            ["agencies.id"],
        ),
        sa.ForeignKeyConstraint(
            ["item_id"],
            ["items.id"],
        ),
        sa.ForeignKeyConstraint(
            ["storage_id"],
            ["agency_storages.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agency_id", "item_id", "storage_id", "expires_on", name="uq_inventory_expiration_balances_key"),
    )
    op.create_index("idx_inventory_expiration_balances_agency_expires", "inventory_expiration_balances", ["agency_id", "expires_on"], unique=False)
    op.create_index(
        "idx_inventory_expiration_balances_agency_item_storage", "inventory_expiration_balances", ["agency_id", "item_id", "storage_id"], unique=False
    )
    op.create_table(
        "inventory_storage_balances",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("agency_id", sa.Integer(), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("storage_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("last_counted_at", sa.DateTime(), nullable=True),
        sa.Column("last_takeout_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["agency_id"],
            ["agencies.id"],
        ),
        sa.ForeignKeyConstraint(
            ["item_id"],
            ["items.id"],
        ),
        sa.ForeignKeyConstraint(
            ["storage_id"],
            ["agency_storages.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agency_id", "item_id", "storage_id", name="uq_inventory_storage_balances_agency_item_storage"),
    )
    op.create_index("idx_inventory_storage_balances_agency_item", "inventory_storage_balances", ["agency_id", "item_id"], unique=False)
    op.create_index("idx_inventory_storage_balances_agency_storage", "inventory_storage_balances", ["agency_id", "storage_id"], unique=False)
    op.create_table(
        "action_log_expiration_lines",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("action_log_id", sa.Integer(), nullable=False),
        sa.Column("expires_on", sa.Date(), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["action_log_id"], ["action_logs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_action_log_expiration_lines_action_log_id"), "action_log_expiration_lines", ["action_log_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_action_log_expiration_lines_action_log_id"), table_name="action_log_expiration_lines")
    op.drop_table("action_log_expiration_lines")
    op.drop_index("idx_inventory_storage_balances_agency_storage", table_name="inventory_storage_balances")
    op.drop_index("idx_inventory_storage_balances_agency_item", table_name="inventory_storage_balances")
    op.drop_table("inventory_storage_balances")
    op.drop_index("idx_inventory_expiration_balances_agency_item_storage", table_name="inventory_expiration_balances")
    op.drop_index("idx_inventory_expiration_balances_agency_expires", table_name="inventory_expiration_balances")
    op.drop_table("inventory_expiration_balances")
    op.drop_index(op.f("ix_alert_notifications_notification_recipient_id"), table_name="alert_notifications")
    op.drop_index(op.f("ix_alert_notifications_email_delivery_id"), table_name="alert_notifications")
    op.drop_index(op.f("ix_alert_notifications_alert_id"), table_name="alert_notifications")
    op.drop_index("idx_alert_notifications_recipient_alert", table_name="alert_notifications")
    op.drop_table("alert_notifications")
    op.drop_index("idx_agency_to_location", table_name="action_logs")
    op.drop_index("idx_agency_item_id", table_name="action_logs")
    op.drop_index("idx_agency_from_location", table_name="action_logs")
    op.drop_index("idx_action_logs_agency_to_operation_time_id", table_name="action_logs")
    op.drop_index("idx_action_logs_agency_item_time_id", table_name="action_logs")
    op.drop_index("idx_action_logs_agency_id_desc", table_name="action_logs")
    op.drop_index("idx_action_logs_agency_from_operation_time_id", table_name="action_logs")
    op.drop_table("action_logs")
    op.drop_index(op.f("ix_unknown_upc_scans_status"), table_name="unknown_upc_scans")
    op.drop_index(op.f("ix_unknown_upc_scans_created_at"), table_name="unknown_upc_scans")
    op.drop_index(op.f("ix_unknown_upc_scans_agency_id"), table_name="unknown_upc_scans")
    op.drop_index("idx_unknown_upc_scans_agency_status_created", table_name="unknown_upc_scans")
    op.drop_table("unknown_upc_scans")
    op.drop_index(op.f("ix_notification_preferences_recipient_id"), table_name="notification_preferences")
    op.drop_index(op.f("ix_notification_preferences_preference_key"), table_name="notification_preferences")
    op.drop_table("notification_preferences")
    op.drop_index(op.f("ix_item_secondary_upcs_item_id"), table_name="item_secondary_upcs")
    op.drop_index(op.f("ix_item_secondary_upcs_agency_id"), table_name="item_secondary_upcs")
    op.drop_index("idx_item_secondary_upcs_agency_upc", table_name="item_secondary_upcs")
    op.drop_index("idx_item_secondary_upcs_agency_item", table_name="item_secondary_upcs")
    op.drop_table("item_secondary_upcs")
    op.drop_index(op.f("ix_inventory_item_location_states_state_version_at"), table_name="inventory_item_location_states")
    op.drop_index(op.f("ix_inventory_item_location_states_item_id"), table_name="inventory_item_location_states")
    op.drop_index(op.f("ix_inventory_item_location_states_agency_location_id"), table_name="inventory_item_location_states")
    op.drop_index(op.f("ix_inventory_item_location_states_agency_id"), table_name="inventory_item_location_states")
    op.drop_index("idx_inventory_item_location_states_signature", table_name="inventory_item_location_states")
    op.drop_table("inventory_item_location_states")
    op.drop_index(op.f("ix_email_deliveries_status"), table_name="email_deliveries")
    op.drop_index(op.f("ix_email_deliveries_sent_at"), table_name="email_deliveries")
    op.drop_index(op.f("ix_email_deliveries_notification_recipient_id"), table_name="email_deliveries")
    op.drop_index(op.f("ix_email_deliveries_kind"), table_name="email_deliveries")
    op.drop_index(op.f("ix_email_deliveries_created_at"), table_name="email_deliveries")
    op.drop_index(op.f("ix_email_deliveries_agency_id"), table_name="email_deliveries")
    op.drop_index("idx_email_deliveries_recipient_kind_sent", table_name="email_deliveries")
    op.drop_table("email_deliveries")
    op.drop_index(
        "uq_alerts_open_dedupe_key", table_name="alerts", postgresql_where=sa.text("status = 'OPEN'"), sqlite_where=sa.text("status = 'OPEN'")
    )
    op.drop_index(op.f("ix_alerts_status"), table_name="alerts")
    op.drop_index(op.f("ix_alerts_opened_at"), table_name="alerts")
    op.drop_index(op.f("ix_alerts_item_id"), table_name="alerts")
    op.drop_index(op.f("ix_alerts_dedupe_key"), table_name="alerts")
    op.drop_index(op.f("ix_alerts_alert_type"), table_name="alerts")
    op.drop_index(op.f("ix_alerts_agency_location_id"), table_name="alerts")
    op.drop_index(op.f("ix_alerts_agency_id"), table_name="alerts")
    op.drop_index("idx_alerts_agency_status_type", table_name="alerts")
    op.drop_table("alerts")
    op.drop_index(op.f("ix_agency_storages_location_id"), table_name="agency_storages")
    op.drop_index(op.f("ix_agency_storages_agency_id"), table_name="agency_storages")
    op.drop_table("agency_storages")
    op.drop_index(op.f("ix_agency_devices_device_token_hash"), table_name="agency_devices")
    op.drop_index(op.f("ix_agency_devices_agency_id"), table_name="agency_devices")
    op.drop_table("agency_devices")
    op.drop_index(op.f("ix_password_reset_pins_expires_at"), table_name="password_reset_pins")
    op.drop_index(op.f("ix_password_reset_pins_agency_id"), table_name="password_reset_pins")
    op.drop_table("password_reset_pins")
    op.drop_index(op.f("ix_notification_recipients_agency_id"), table_name="notification_recipients")
    op.drop_table("notification_recipients")
    op.drop_index("idx_agency_upc", table_name="items")
    op.drop_index("idx_agency_name", table_name="items")
    op.drop_index("idx_agency_last_accessed", table_name="items")
    op.drop_table("items")
    op.drop_index(op.f("ix_agency_locations_agency_id"), table_name="agency_locations")
    op.drop_table("agency_locations")
    op.drop_index(op.f("ix_agency_item_tags_agency_id"), table_name="agency_item_tags")
    op.drop_table("agency_item_tags")
    op.drop_index(op.f("ix_scheduler_runs_status"), table_name="scheduler_runs")
    op.drop_index(op.f("ix_scheduler_runs_period_key"), table_name="scheduler_runs")
    op.drop_index(op.f("ix_scheduler_runs_job_name"), table_name="scheduler_runs")
    op.drop_index(op.f("ix_scheduler_runs_agency_id"), table_name="scheduler_runs")
    op.drop_table("scheduler_runs")
    op.drop_table("agencies")
