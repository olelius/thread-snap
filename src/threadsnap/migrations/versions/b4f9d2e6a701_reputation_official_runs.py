"""add official reputation scheduling, retries, and deletion

Revision ID: b4f9d2e6a701
Revises: f2a8c5d7e901
Create Date: 2026-08-25
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b4f9d2e6a701"
down_revision: Union[str, Sequence[str], None] = "f2a8c5d7e901"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "reputation_runs",
        sa.Column("report_attempt_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "reputation_runs",
        sa.Column("target_keys", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.add_column("reputation_runs", sa.Column("root_run_id", sa.String(36)))
    op.add_column("reputation_runs", sa.Column("parent_run_id", sa.String(36)))
    op.add_column("reputation_runs", sa.Column("scope_version_id", sa.String(36)))
    op.add_column("reputation_runs", sa.Column("schedule_type", sa.String(32)))
    op.add_column("reputation_runs", sa.Column("idempotency_key", sa.String(96)))
    op.add_column("reputation_runs", sa.Column("planned_at", sa.DateTime(timezone=True)))
    op.add_column("reputation_runs", sa.Column("report_planned_at", sa.DateTime(timezone=True)))
    op.add_column("reputation_runs", sa.Column("report_generated_at", sa.DateTime(timezone=True)))
    op.add_column(
        "reputation_runs",
        sa.Column("delayed", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("reputation_runs", sa.Column("concurrency", sa.Integer()))
    op.add_column("reputation_runs", sa.Column("baseline_date", sa.String(10)))
    op.add_column("reputation_runs", sa.Column("baseline_frozen_at", sa.DateTime(timezone=True)))
    op.add_column("reputation_runs", sa.Column("baseline_source_run_id", sa.String(36)))
    op.add_column(
        "reputation_runs",
        sa.Column("baseline_snapshot", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.create_index("ix_reputation_runs_root", "reputation_runs", ["root_run_id", "created_at"])
    op.create_index(
        "ux_reputation_runs_idempotency",
        "reputation_runs",
        ["idempotency_key"],
        unique=True,
    )

    op.add_column(
        "reputation_results",
        sa.Column("mapping_snapshot", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "reputation_results",
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column("reputation_results", sa.Column("duration_ms", sa.Integer()))

    op.create_table(
        "reputation_schedule_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("planned_date", sa.String(10), nullable=False),
        sa.Column("run_type", sa.String(32), nullable=False),
        sa.Column("planned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("scope_version_id", sa.String(36)),
        sa.Column("run_id", sa.String(36)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("planned_date", "run_type", name="uq_reputation_schedule_event"),
    )
    op.create_index(
        "ix_reputation_schedule_events_planned", "reputation_schedule_events", ["planned_at"]
    )
    op.create_table(
        "reputation_scheduler_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "reputation_tombstones",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("planned_date", sa.String(10), nullable=False),
        sa.Column("run_type", sa.String(32), nullable=False),
        sa.Column("idempotency_key", sa.String(96), nullable=False, unique=True),
        sa.Column("original_run_id", sa.String(36), nullable=False),
        sa.Column("result_hash", sa.String(64), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("planned_date", "run_type", name="uq_reputation_tombstone"),
    )
    op.create_table(
        "reputation_delete_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("root_run_id", sa.String(36), nullable=False),
        sa.Column("idempotency_key", sa.String(96), nullable=False, unique=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("manifest", sa.JSON(), nullable=False),
        sa.Column("quarantine_path", sa.Text(), nullable=False),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_reputation_delete_jobs_status",
        "reputation_delete_jobs",
        ["status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_reputation_delete_jobs_status", table_name="reputation_delete_jobs")
    op.drop_table("reputation_delete_jobs")
    op.drop_table("reputation_tombstones")
    op.drop_table("reputation_scheduler_state")
    op.drop_index(
        "ix_reputation_schedule_events_planned", table_name="reputation_schedule_events"
    )
    op.drop_table("reputation_schedule_events")
    op.drop_column("reputation_results", "duration_ms")
    op.drop_column("reputation_results", "attempt_count")
    op.drop_column("reputation_results", "mapping_snapshot")
    op.drop_index("ux_reputation_runs_idempotency", table_name="reputation_runs")
    op.drop_index("ix_reputation_runs_root", table_name="reputation_runs")
    for name in (
        "baseline_source_run_id",
        "baseline_snapshot",
        "baseline_frozen_at",
        "baseline_date",
        "concurrency",
        "delayed",
        "report_generated_at",
        "report_planned_at",
        "planned_at",
        "idempotency_key",
        "scope_version_id",
        "schedule_type",
        "parent_run_id",
        "root_run_id",
        "target_keys",
        "report_attempt_count",
    ):
        op.drop_column("reputation_runs", name)
