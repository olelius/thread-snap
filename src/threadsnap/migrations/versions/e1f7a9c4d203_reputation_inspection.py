"""add reputation inspection domain

Revision ID: e1f7a9c4d203
Revises: d4e8f6a1b203
Create Date: 2026-08-24
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e1f7a9c4d203"
down_revision: Union[str, Sequence[str], None] = "d4e8f6a1b203"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "reputation_scope_drafts",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("published_version_id", sa.String(36)),
        sa.Column("source_sha256", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "reputation_scope_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False, unique=True),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("source_revision", sa.Integer(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "reputation_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("number", sa.String(40), nullable=False, unique=True),
        sa.Column("source_type", sa.String(24), nullable=False),
        sa.Column("scenario_id", sa.String(48)),
        sa.Column("fixture_version", sa.String(32)),
        sa.Column("input_hash", sa.String(64)),
        sa.Column("run_type", sa.String(32), nullable=False),
        sa.Column("planned_date", sa.String(10), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("platform_codes", sa.JSON(), nullable=False),
        sa.Column("planned_count", sa.Integer(), nullable=False),
        sa.Column("completed_count", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("required_evidence_count", sa.Integer(), nullable=False),
        sa.Column("complete_evidence_count", sa.Integer(), nullable=False),
        sa.Column("report_status", sa.String(32), nullable=False),
        sa.Column("report_text", sa.Text()),
        sa.Column("report_path", sa.Text()),
        sa.Column("xlsx_path", sa.Text()),
        sa.Column("evidence_zip_path", sa.Text()),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_reputation_runs_created", "reputation_runs", ["source_type", "created_at"])
    op.create_index("ix_reputation_runs_status", "reputation_runs", ["status", "created_at"])
    op.create_table(
        "reputation_results",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("vehicle_id", sa.String(64), nullable=False),
        sa.Column("series_name", sa.String(120), nullable=False),
        sa.Column("vehicle_name", sa.String(160), nullable=False),
        sa.Column("role", sa.String(24), nullable=False),
        sa.Column("role_position", sa.Integer(), nullable=False),
        sa.Column("vehicle_position", sa.Integer(), nullable=False),
        sa.Column("platform_code", sa.String(32), nullable=False),
        sa.Column("platform_name", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("evidence_required", sa.Boolean(), nullable=False),
        sa.Column("error_code", sa.String(64)),
        sa.Column("error_message", sa.Text()),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["reputation_runs.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("run_id", "vehicle_id", "platform_code", name="uq_reputation_result"),
    )
    op.create_index(
        "ix_reputation_results_run_order",
        "reputation_results",
        ["run_id", "role_position", "vehicle_position"],
    )
    op.create_table(
        "reputation_evidence",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("result_id", sa.String(36), nullable=False, unique=True),
        sa.Column("full_page_path", sa.Text(), nullable=False),
        sa.Column("metric_region_path", sa.Text(), nullable=False),
        sa.Column("full_page_sha256", sa.String(64), nullable=False),
        sa.Column("metric_region_sha256", sa.String(64), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["result_id"], ["reputation_results.id"], ondelete="CASCADE"),
    )


def downgrade() -> None:
    op.drop_table("reputation_evidence")
    op.drop_index("ix_reputation_results_run_order", table_name="reputation_results")
    op.drop_table("reputation_results")
    op.drop_index("ix_reputation_runs_status", table_name="reputation_runs")
    op.drop_index("ix_reputation_runs_created", table_name="reputation_runs")
    op.drop_table("reputation_runs")
    op.drop_table("reputation_scope_versions")
    op.drop_table("reputation_scope_drafts")
