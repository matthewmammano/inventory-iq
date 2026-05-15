"""Store alert rows per recipient.

Revision ID: 20260514_0003
Revises: 20260510_0002
Create Date: 2026-05-14
"""

import sqlalchemy as sa
from alembic import op

revision = "20260514_0003"
down_revision = "20260510_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = _columns()
    indexes = _indexes()
    if "agency_email_id" in columns and "scheduled" not in columns:
        return

    op.execute("DELETE FROM alert_records")
    with op.batch_alter_table("alert_records") as batch_op:
        if "ix_alert_records_scheduled" in indexes:
            batch_op.drop_index("ix_alert_records_scheduled")
        if "scheduled" in columns:
            batch_op.drop_column("scheduled")
        if "agency_email_id" not in columns:
            batch_op.add_column(sa.Column("agency_email_id", sa.Integer(), nullable=False))
            batch_op.create_index("ix_alert_records_agency_email_id", ["agency_email_id"])
            batch_op.create_foreign_key(
                "fk_alert_records_agency_email_id",
                "agency_emails",
                ["agency_email_id"],
                ["id"],
                ondelete="CASCADE",
            )


def downgrade() -> None:
    columns = _columns()
    indexes = _indexes()
    if "scheduled" in columns and "agency_email_id" not in columns:
        return

    op.execute("DELETE FROM alert_records")
    with op.batch_alter_table("alert_records") as batch_op:
        if "agency_email_id" in columns:
            batch_op.drop_constraint("fk_alert_records_agency_email_id", type_="foreignkey")
            if "ix_alert_records_agency_email_id" in indexes:
                batch_op.drop_index("ix_alert_records_agency_email_id")
            batch_op.drop_column("agency_email_id")
        if "scheduled" not in columns:
            batch_op.add_column(sa.Column("scheduled", sa.DateTime(), nullable=False))
            batch_op.create_index("ix_alert_records_scheduled", ["scheduled"])


def _columns() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {column["name"] for column in inspector.get_columns("alert_records")}


def _indexes() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {
        name
        for index in inspector.get_indexes("alert_records")
        if (name := index["name"]) is not None
    }
