"""Track stock alert episodes and delivery state keys.

Revision ID: 20260628_0019
Revises: 20260627_0018
Create Date: 2026-06-28
"""

import sqlalchemy as sa
from alembic import op

revision = "20260628_0019"
down_revision = "20260627_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "notification_email_deliveries" in tables:
        columns = {column["name"] for column in inspector.get_columns("notification_email_deliveries")}
        if "state_alert_keys_json" not in columns:
            with op.batch_alter_table("notification_email_deliveries") as batch_op:
                batch_op.add_column(sa.Column("state_alert_keys_json", sa.JSON(), nullable=False, server_default="[]"))

    if "inventory_item_location_states" in tables:
        columns = {column["name"] for column in inspector.get_columns("inventory_item_location_states")}
        if "effective_alert_started_at" not in columns:
            with op.batch_alter_table("inventory_item_location_states") as batch_op:
                batch_op.add_column(sa.Column("effective_alert_started_at", sa.DateTime(), nullable=True))
            bind.execute(
                sa.text(
                    """
                    UPDATE inventory_item_location_states
                    SET effective_alert_started_at = COALESCE(state_version_at, updated_at, CURRENT_TIMESTAMP)
                    WHERE effective_alert_type IS NOT NULL
                      AND effective_alert_started_at IS NULL
                    """
                )
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "inventory_item_location_states" in tables:
        columns = {column["name"] for column in inspector.get_columns("inventory_item_location_states")}
        if "effective_alert_started_at" in columns:
            with op.batch_alter_table("inventory_item_location_states") as batch_op:
                batch_op.drop_column("effective_alert_started_at")

    if "notification_email_deliveries" in tables:
        columns = {column["name"] for column in inspector.get_columns("notification_email_deliveries")}
        if "state_alert_keys_json" in columns:
            with op.batch_alter_table("notification_email_deliveries") as batch_op:
                batch_op.drop_column("state_alert_keys_json")
