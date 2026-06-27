"""Add per-recipient notification quiet hours.

Revision ID: 20260627_0019
Revises: 20260627_0018
Create Date: 2026-06-27
"""

import sqlalchemy as sa
from alembic import op

revision = "20260627_0019"
down_revision = "20260627_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
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


def downgrade() -> None:
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


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def _check_constraints(table_name: str) -> set[str]:
    return {constraint["name"] for constraint in sa.inspect(op.get_bind()).get_check_constraints(table_name) if constraint["name"] is not None}
