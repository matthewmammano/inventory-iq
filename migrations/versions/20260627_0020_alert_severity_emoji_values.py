"""Rewrite persisted alert severity names to the new severity set.

Revision ID: 20260627_0020
Revises: 20260627_0019
Create Date: 2026-06-27
"""

import sqlalchemy as sa
from alembic import op

revision = "20260627_0020"
down_revision = "20260627_0019"
branch_labels = None
depends_on = None

UPGRADE_MAP = {"WARNING": "MEDIUM", "NOTICE": "LOW"}
DOWNGRADE_MAP = {"MEDIUM": "WARNING", "LOW": "NOTICE"}


def upgrade() -> None:
    _rewrite("inventory_alert_events", "severity", UPGRADE_MAP)
    _rewrite("inventory_item_location_states", "effective_severity", UPGRADE_MAP)


def downgrade() -> None:
    _rewrite("inventory_alert_events", "severity", DOWNGRADE_MAP)
    _rewrite("inventory_item_location_states", "effective_severity", DOWNGRADE_MAP)


def _rewrite(table_name: str, column_name: str, mapping: dict[str, str]) -> None:
    if table_name not in _tables() or column_name not in _columns(table_name):
        return

    bind = op.get_bind()
    for old_value, new_value in mapping.items():
        bind.execute(
            sa.text(f"UPDATE {table_name} SET {column_name} = :new_value WHERE {column_name} = :old_value"),
            {"new_value": new_value, "old_value": old_value},
        )


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}
