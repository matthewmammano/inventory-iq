"""Store scheduler run markers in the database.

Revision ID: 20260525_0006
Revises: 20260525_0005
Create Date: 2026-05-25
"""

import sqlalchemy as sa
from alembic import op

revision = "20260525_0006"
down_revision = "20260525_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "scheduler_runs" in _tables():
        return
    op.create_table(
        "scheduler_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_name", sa.String(length=80), nullable=False),
        sa.Column("agency_id", sa.Integer(), nullable=False),
        sa.Column("period_key", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.UniqueConstraint(
            "job_name",
            "agency_id",
            "period_key",
            name="uq_scheduler_runs_job_agency_period",
        ),
    )
    op.create_index("ix_scheduler_runs_job_name", "scheduler_runs", ["job_name"])
    op.create_index("ix_scheduler_runs_agency_id", "scheduler_runs", ["agency_id"])
    op.create_index("ix_scheduler_runs_period_key", "scheduler_runs", ["period_key"])
    op.create_index("ix_scheduler_runs_status", "scheduler_runs", ["status"])


def downgrade() -> None:
    if "scheduler_runs" not in _tables():
        return
    op.drop_index("ix_scheduler_runs_status", table_name="scheduler_runs")
    op.drop_index("ix_scheduler_runs_period_key", table_name="scheduler_runs")
    op.drop_index("ix_scheduler_runs_agency_id", table_name="scheduler_runs")
    op.drop_index("ix_scheduler_runs_job_name", table_name="scheduler_runs")
    op.drop_table("scheduler_runs")


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())
