"""Add expiration tracking and normalized notification preferences.

Revision ID: 20260706_0024
Revises: 20260701_0023
Create Date: 2026-07-06
"""

import sqlalchemy as sa
from alembic import op

revision = "20260706_0024"
down_revision = "20260701_0023"
branch_labels = None
depends_on = None

OLD_RECIPIENT_TABLE = "agency_emails"
RECIPIENT_TABLE = "notification_recipients"
PREFERENCE_TABLE = "notification_preferences"
EXPIRATION_BALANCE_TABLE = "inventory_expiration_balances"
ACTION_EXPIRATION_LINE_TABLE = "action_log_expiration_lines"

LEGACY_PREFERENCES = {
    "alert_for_stockout": "STOCKOUT",
    "alert_for_stockout_pred": "STOCKOUT_FORECAST",
    "alert_for_low": "LOW_STOCK",
    "alert_for_low_pred": "LOW_STOCK_FORECAST",
    "alert_for_stale_count": "STALE_COUNT",
    "alert_for_rare_takeout": "RARE_TAKEOUT",
    "alert_for_count": "COUNT_ACTION",
    "alert_for_restock": "RESTOCK_ACTION",
    "alert_for_takeout": "TAKEOUT_ACTION",
    "alert_for_transfer": "TRANSFER_ACTION",
    "daily_summary": "DAILY_SUMMARY",
    "weekly_summary": "WEEKLY_SUMMARY",
    "monthly_summary": "MONTHLY_SUMMARY",
    "yearly_summary": "YEARLY_SUMMARY",
}
NEW_PREFERENCES = ("EXPIRED_STOCK", "EXPIRING_SOON", "EXPIRATION_COUNT_NEEDED")


def upgrade() -> None:
    _rename_table(OLD_RECIPIENT_TABLE, RECIPIENT_TABLE)
    _add_expiration_settings()
    _rename_action_log_columns()
    _rename_delivery_recipient_column()
    _create_notification_preferences()
    _backfill_notification_preferences()
    _drop_legacy_notification_columns()
    _create_expiration_tables()
    _drop_storage_balance_last_activity()


def downgrade() -> None:
    _add_storage_balance_last_activity()
    _drop_expiration_tables()
    _restore_legacy_notification_columns()
    _backfill_legacy_notification_columns()
    if PREFERENCE_TABLE in _tables():
        op.drop_table(PREFERENCE_TABLE)
    _rename_delivery_recipient_column(reverse=True)
    _rename_action_log_columns(reverse=True)
    _drop_expiration_settings()
    _rename_table(RECIPIENT_TABLE, OLD_RECIPIENT_TABLE)


def _add_expiration_settings() -> None:
    if "agencies" in _tables() and "expiration_notice_days" not in _columns("agencies"):
        with op.batch_alter_table("agencies") as batch_op:
            batch_op.add_column(sa.Column("expiration_notice_days", sa.Integer(), nullable=False, server_default="30"))
    if "items" in _tables():
        columns = _columns("items")
        with op.batch_alter_table("items") as batch_op:
            if "expiration_tracking_enabled" not in columns:
                batch_op.add_column(sa.Column("expiration_tracking_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
            if "expiration_notice_days_override" not in columns:
                batch_op.add_column(sa.Column("expiration_notice_days_override", sa.Integer(), nullable=True))


def _drop_expiration_settings() -> None:
    if "items" in _tables():
        columns = _columns("items")
        with op.batch_alter_table("items") as batch_op:
            if "expiration_notice_days_override" in columns:
                batch_op.drop_column("expiration_notice_days_override")
            if "expiration_tracking_enabled" in columns:
                batch_op.drop_column("expiration_tracking_enabled")
    if "agencies" in _tables() and "expiration_notice_days" in _columns("agencies"):
        with op.batch_alter_table("agencies") as batch_op:
            batch_op.drop_column("expiration_notice_days")


def _rename_action_log_columns(*, reverse: bool = False) -> None:
    if "action_logs" not in _tables():
        return
    rename_pairs = (
        ("quantity", "quantity_delta"),
        ("from_storage_id", "from_location_id"),
        ("to_storage_id", "to_location_id"),
    )
    if reverse:
        rename_pairs = tuple((new, old) for new, old in rename_pairs)
    columns = _columns("action_logs")
    with op.batch_alter_table("action_logs") as batch_op:
        for target, source in rename_pairs:
            if source in columns and target not in columns:
                batch_op.alter_column(source, new_column_name=target)


def _rename_delivery_recipient_column(*, reverse: bool = False) -> None:
    if "notification_email_deliveries" not in _tables():
        return
    source, target = ("notification_recipient_id", "agency_email_id") if reverse else ("agency_email_id", "notification_recipient_id")
    columns = _columns("notification_email_deliveries")
    if source not in columns or target in columns:
        return
    with op.batch_alter_table("notification_email_deliveries") as batch_op:
        batch_op.alter_column(source, new_column_name=target)


def _create_notification_preferences() -> None:
    if PREFERENCE_TABLE in _tables():
        return
    op.create_table(
        PREFERENCE_TABLE,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("recipient_id", sa.Integer(), sa.ForeignKey(f"{RECIPIENT_TABLE}.id", ondelete="CASCADE"), nullable=False),
        sa.Column("preference_key", sa.String(length=32), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("recipient_id", "preference_key", name="uq_notification_preferences_recipient_key"),
    )
    op.create_index("ix_notification_preferences_recipient_id", PREFERENCE_TABLE, ["recipient_id"])
    op.create_index("ix_notification_preferences_preference_key", PREFERENCE_TABLE, ["preference_key"])


def _backfill_notification_preferences() -> None:
    if RECIPIENT_TABLE not in _tables() or PREFERENCE_TABLE not in _tables():
        return
    bind = op.get_bind()
    columns = _columns(RECIPIENT_TABLE)
    for legacy_column, preference_key in LEGACY_PREFERENCES.items():
        if legacy_column not in columns:
            continue
        bind.execute(
            _preference_sql(
                f"""
                INSERT INTO notification_preferences (recipient_id, preference_key, enabled)
                SELECT id, :preference_key, COALESCE({legacy_column}, FALSE)
                FROM notification_recipients
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM notification_preferences existing
                    WHERE existing.recipient_id = notification_recipients.id
                      AND existing.preference_key = :preference_key
                )
                """
            ),
            {"preference_key": preference_key},
        )
    for preference_key in NEW_PREFERENCES:
        bind.execute(
            _preference_sql(
                """
                INSERT INTO notification_preferences (recipient_id, preference_key, enabled)
                SELECT id, :preference_key, TRUE
                FROM notification_recipients
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM notification_preferences existing
                    WHERE existing.recipient_id = notification_recipients.id
                      AND existing.preference_key = :preference_key
                )
                """
            ),
            {"preference_key": preference_key},
        )


def _drop_legacy_notification_columns() -> None:
    if RECIPIENT_TABLE not in _tables():
        return
    columns = _columns(RECIPIENT_TABLE)
    with op.batch_alter_table(RECIPIENT_TABLE) as batch_op:
        for column_name in LEGACY_PREFERENCES:
            if column_name in columns:
                batch_op.drop_column(column_name)


def _restore_legacy_notification_columns() -> None:
    if RECIPIENT_TABLE not in _tables():
        return
    columns = _columns(RECIPIENT_TABLE)
    with op.batch_alter_table(RECIPIENT_TABLE) as batch_op:
        for column_name in LEGACY_PREFERENCES:
            if column_name not in columns:
                batch_op.add_column(sa.Column(column_name, sa.Boolean(), nullable=False, server_default=sa.false()))


def _backfill_legacy_notification_columns() -> None:
    if RECIPIENT_TABLE not in _tables() or PREFERENCE_TABLE not in _tables():
        return
    bind = op.get_bind()
    for legacy_column, preference_key in LEGACY_PREFERENCES.items():
        if legacy_column not in _columns(RECIPIENT_TABLE):
            continue
        bind.execute(
            _preference_sql(
                f"""
                UPDATE notification_recipients
                SET {legacy_column} = COALESCE((
                    SELECT enabled
                    FROM notification_preferences preferences
                    WHERE preferences.recipient_id = notification_recipients.id
                      AND preferences.preference_key = :preference_key
                ), FALSE)
                """
            ),
            {"preference_key": preference_key},
        )


def _preference_sql(sql: str):
    return sa.text(sql).bindparams(sa.bindparam("preference_key", type_=sa.String(length=32)))


def _create_expiration_tables() -> None:
    if EXPIRATION_BALANCE_TABLE not in _tables():
        op.create_table(
            EXPIRATION_BALANCE_TABLE,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("agency_id", sa.Integer(), sa.ForeignKey("agencies.id"), nullable=False),
            sa.Column("item_id", sa.Integer(), sa.ForeignKey("items.id"), nullable=False),
            sa.Column("storage_id", sa.Integer(), sa.ForeignKey("agency_storages.id"), nullable=False),
            sa.Column("expires_on", sa.Date(), nullable=False),
            sa.Column("quantity", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_counted_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.UniqueConstraint("agency_id", "item_id", "storage_id", "expires_on", name="uq_inventory_expiration_balances_key"),
        )
        op.create_index(
            "idx_inventory_expiration_balances_agency_item_storage",
            EXPIRATION_BALANCE_TABLE,
            ["agency_id", "item_id", "storage_id"],
        )
        op.create_index("idx_inventory_expiration_balances_agency_expires", EXPIRATION_BALANCE_TABLE, ["agency_id", "expires_on"])
    if ACTION_EXPIRATION_LINE_TABLE not in _tables():
        op.create_table(
            ACTION_EXPIRATION_LINE_TABLE,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("action_log_id", sa.Integer(), sa.ForeignKey("action_logs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("expires_on", sa.Date(), nullable=True),
            sa.Column("quantity", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        op.create_index("ix_action_log_expiration_lines_action_log_id", ACTION_EXPIRATION_LINE_TABLE, ["action_log_id"])


def _drop_expiration_tables() -> None:
    if ACTION_EXPIRATION_LINE_TABLE in _tables():
        op.drop_table(ACTION_EXPIRATION_LINE_TABLE)
    if EXPIRATION_BALANCE_TABLE in _tables():
        op.drop_table(EXPIRATION_BALANCE_TABLE)


def _drop_storage_balance_last_activity() -> None:
    if "inventory_storage_balances" in _tables() and "last_activity_at" in _columns("inventory_storage_balances"):
        with op.batch_alter_table("inventory_storage_balances") as batch_op:
            batch_op.drop_column("last_activity_at")


def _add_storage_balance_last_activity() -> None:
    if "inventory_storage_balances" in _tables() and "last_activity_at" not in _columns("inventory_storage_balances"):
        with op.batch_alter_table("inventory_storage_balances") as batch_op:
            batch_op.add_column(sa.Column("last_activity_at", sa.DateTime(), nullable=True))


def _rename_table(old_name: str, new_name: str) -> None:
    tables = _tables()
    if old_name in tables and new_name not in tables:
        op.rename_table(old_name, new_name)


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}
