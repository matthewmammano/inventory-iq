"""Apply alert delivery model updates.

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

UPGRADE_SEVERITY_MAP = {"WARNING": "MEDIUM", "NOTICE": "LOW"}
DOWNGRADE_SEVERITY_MAP = {"MEDIUM": "WARNING", "LOW": "NOTICE"}
EVENT_SEVERITY_BY_TYPE = {
    "STOCKOUT": "CRITICAL",
    "STOCKOUT_FORECAST": "HIGH",
    "LOW_STOCK": "MEDIUM",
    "LOW_STOCK_FORECAST": "LOW",
    "STALE_COUNT": "LOW",
    "RARE_TAKEOUT": "LOW",
    "UNKNOWN_UPC": "LOW",
    "COUNT_ACTION": "INFO",
    "RESTOCK_ACTION": "INFO",
    "TAKEOUT_ACTION": "INFO",
    "TRANSFER_ACTION": "INFO",
}
STATE_SEVERITY_BY_TYPE = {
    "STOCKOUT": "CRITICAL",
    "STOCKOUT_FORECAST": "HIGH",
    "LOW_STOCK": "MEDIUM",
    "LOW_STOCK_FORECAST": "LOW",
}


def upgrade() -> None:
    _simplify_notification_deliveries()
    _add_quiet_hours()
    _rewrite_alert_severities(UPGRADE_SEVERITY_MAP)
    _rewrite_event_severities(EVENT_SEVERITY_BY_TYPE)
    _rewrite_state_severities(STATE_SEVERITY_BY_TYPE)


def downgrade() -> None:
    _rewrite_alert_severities(DOWNGRADE_SEVERITY_MAP)
    _drop_quiet_hours()
    _restore_notification_delivery_legacy_columns()


def _simplify_notification_deliveries() -> None:
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

    if "idx_notification_email_deliveries_recipient_send" in _indexes("notification_email_deliveries"):
        op.drop_index("idx_notification_email_deliveries_recipient_send", table_name="notification_email_deliveries")

    _delete_duplicate_recipient_send_rows()
    with op.batch_alter_table("notification_email_deliveries") as batch_op:
        if "uq_notification_email_deliveries_recipient_send" not in _unique_constraints("notification_email_deliveries"):
            batch_op.create_unique_constraint(
                "uq_notification_email_deliveries_recipient_send",
                ["agency_id", "agency_email_id", "send_at"],
            )


def _restore_notification_delivery_legacy_columns() -> None:
    if "notification_email_deliveries" not in _tables():
        return

    with op.batch_alter_table("notification_email_deliveries") as batch_op:
        if "uq_notification_email_deliveries_recipient_send" in _unique_constraints("notification_email_deliveries"):
            batch_op.drop_constraint("uq_notification_email_deliveries_recipient_send", type_="unique")

    columns = _columns("notification_email_deliveries")
    with op.batch_alter_table("notification_email_deliveries") as batch_op:
        if "notification_kind" not in columns:
            batch_op.add_column(sa.Column("notification_kind", sa.String(length=32), nullable=False, server_default="HOURLY_DIGEST"))
        if "dedupe_key" not in columns:
            batch_op.add_column(sa.Column("dedupe_key", sa.String(length=255), nullable=True))

    op.execute(sa.text("UPDATE notification_email_deliveries SET dedupe_key = 'LEGACY:' || id WHERE dedupe_key IS NULL"))

    indexes = _indexes("notification_email_deliveries")
    if "ix_notification_email_deliveries_notification_kind" not in indexes:
        op.create_index("ix_notification_email_deliveries_notification_kind", "notification_email_deliveries", ["notification_kind"])
    if "ix_notification_email_deliveries_dedupe_key" not in indexes:
        op.create_index("ix_notification_email_deliveries_dedupe_key", "notification_email_deliveries", ["dedupe_key"])

    with op.batch_alter_table("notification_email_deliveries") as batch_op:
        if "uq_notification_email_deliveries_recipient_dedupe" not in _unique_constraints("notification_email_deliveries"):
            batch_op.create_unique_constraint(
                "uq_notification_email_deliveries_recipient_dedupe",
                ["agency_id", "agency_email_id", "dedupe_key"],
            )


def _add_quiet_hours() -> None:
    if "agency_emails" not in _tables():
        return

    columns = _columns("agency_emails")
    with op.batch_alter_table("agency_emails") as batch_op:
        if "quiet_start_time" not in columns:
            batch_op.add_column(sa.Column("quiet_start_time", sa.String(length=5), nullable=True))
        if "quiet_end_time" not in columns:
            batch_op.add_column(sa.Column("quiet_end_time", sa.String(length=5), nullable=True))
        if "ck_agency_emails_quiet_hours_pair" not in _check_constraints("agency_emails"):
            batch_op.create_check_constraint(
                "ck_agency_emails_quiet_hours_pair",
                "(quiet_start_time IS NULL AND quiet_end_time IS NULL) OR (quiet_start_time IS NOT NULL AND quiet_end_time IS NOT NULL)",
            )


def _drop_quiet_hours() -> None:
    if "agency_emails" not in _tables():
        return

    columns = _columns("agency_emails")
    with op.batch_alter_table("agency_emails") as batch_op:
        if "ck_agency_emails_quiet_hours_pair" in _check_constraints("agency_emails"):
            batch_op.drop_constraint("ck_agency_emails_quiet_hours_pair", type_="check")
        if "quiet_end_time" in columns:
            batch_op.drop_column("quiet_end_time")
        if "quiet_start_time" in columns:
            batch_op.drop_column("quiet_start_time")


def _rewrite_alert_severities(mapping: dict[str, str]) -> None:
    _rewrite_column_values("inventory_alert_events", "severity", mapping)
    _rewrite_column_values("inventory_item_location_states", "effective_severity", mapping)


def _rewrite_event_severities(severities_by_type: dict[str, str]) -> None:
    _rewrite_severities("inventory_alert_events", "alert_type", "severity", severities_by_type)


def _rewrite_state_severities(severities_by_type: dict[str, str]) -> None:
    _rewrite_severities("inventory_item_location_states", "effective_alert_type", "effective_severity", severities_by_type)


def _rewrite_severities(
    table_name: str,
    type_column: str,
    severity_column: str,
    severities_by_type: dict[str, str],
) -> None:
    if table_name not in _tables() or not {type_column, severity_column}.issubset(_columns(table_name)):
        return

    bind = op.get_bind()
    for alert_type, severity in severities_by_type.items():
        bind.execute(
            sa.text(f"UPDATE {table_name} SET {severity_column} = :severity WHERE {type_column} = :alert_type"),
            {"severity": severity, "alert_type": alert_type},
        )


def _rewrite_column_values(table_name: str, column_name: str, mapping: dict[str, str]) -> None:
    if table_name not in _tables() or column_name not in _columns(table_name):
        return

    bind = op.get_bind()
    for old_value, new_value in mapping.items():
        bind.execute(
            sa.text(f"UPDATE {table_name} SET {column_name} = :new_value WHERE {column_name} = :old_value"),
            {"new_value": new_value, "old_value": old_value},
        )


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


def _check_constraints(table_name: str) -> set[str]:
    return {constraint["name"] for constraint in sa.inspect(op.get_bind()).get_check_constraints(table_name) if constraint["name"] is not None}
