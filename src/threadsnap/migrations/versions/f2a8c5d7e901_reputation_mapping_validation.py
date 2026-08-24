"""add reputation mapping validation history

Revision ID: f2a8c5d7e901
Revises: e1f7a9c4d203
Create Date: 2026-08-24
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f2a8c5d7e901"
down_revision: Union[str, Sequence[str], None] = "e1f7a9c4d203"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "reputation_mapping_validation_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("platform_code", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("concurrency", sa.Integer(), nullable=False),
        sa.Column("requested_count", sa.Integer(), nullable=False),
        sa.Column("succeeded_count", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_reputation_mapping_validation_runs_created",
        "reputation_mapping_validation_runs",
        ["created_at"],
    )
    op.create_table(
        "reputation_mapping_validation_attempts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("vehicle_id", sa.String(64), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("mapping_hash", sa.String(64), nullable=False),
        sa.Column("contract_version", sa.String(64), nullable=False),
        sa.Column("adapter_version", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("actual_name", sa.String(160)),
        sa.Column("final_url", sa.Text()),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("gate_results", sa.JSON(), nullable=False),
        sa.Column("full_page_path", sa.Text()),
        sa.Column("metric_region_path", sa.Text()),
        sa.Column("full_page_sha256", sa.String(64)),
        sa.Column("metric_region_sha256", sa.String(64)),
        sa.Column("error_code", sa.String(64)),
        sa.Column("error_message", sa.Text()),
        sa.Column("duration_ms", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"], ["reputation_mapping_validation_runs.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "run_id",
            "vehicle_id",
            "attempt_number",
            name="uq_reputation_mapping_validation_attempt",
        ),
    )
    op.create_index(
        "ix_reputation_mapping_validation_attempts_run",
        "reputation_mapping_validation_attempts",
        ["run_id", "vehicle_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_reputation_mapping_validation_attempts_run",
        table_name="reputation_mapping_validation_attempts",
    )
    op.drop_table("reputation_mapping_validation_attempts")
    op.drop_index(
        "ix_reputation_mapping_validation_runs_created",
        table_name="reputation_mapping_validation_runs",
    )
    op.drop_table("reputation_mapping_validation_runs")
