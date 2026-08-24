"""add synchronized circle page evidence and screenshot artifacts

Revision ID: f8b6c2d4e901
Revises: c6f1e2a93b47
Create Date: 2026-08-22
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f8b6c2d4e901"
down_revision: Union[str, Sequence[str], None] = "c6f1e2a93b47"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "circle_page_evidence",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("circle_task_id", sa.String(36), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("exact_url", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("adapter_version", sa.String(64), nullable=False),
        sa.Column("viewport_width", sa.Integer(), nullable=False),
        sa.Column("viewport_height", sa.Integer(), nullable=False),
        sa.Column("document_width", sa.Integer(), nullable=False),
        sa.Column("document_height", sa.Integer(), nullable=False),
        sa.Column("screenshot_path", sa.Text(), nullable=False),
        sa.Column("screenshot_sha256", sa.String(64), nullable=False),
        sa.Column("manifest_path", sa.Text(), nullable=False),
        sa.Column("manifest_sha256", sa.String(64), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("error_message", sa.Text()),
        sa.ForeignKeyConstraint(["run_id"], ["extraction_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["circle_task_id"], ["circle_tasks.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "circle_task_id", "page_number", name="uq_circle_page_evidence_task_page"
        ),
    )
    op.create_index(
        "ix_circle_page_evidence_run", "circle_page_evidence", ["run_id", "circle_task_id"]
    )
    op.create_table(
        "circle_page_evidence_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("evidence_id", sa.String(36), nullable=False),
        sa.Column("circle_task_id", sa.String(36), nullable=False),
        sa.Column("post_snapshot_id", sa.String(36)),
        sa.Column("platform_post_id", sa.String(80), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("source_position", sa.Integer(), nullable=False),
        sa.Column("x", sa.Integer(), nullable=False),
        sa.Column("y", sa.Integer(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("text_sha256", sa.String(64), nullable=False),
        sa.Column("image_count", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["evidence_id"], ["circle_page_evidence.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["circle_task_id"], ["circle_tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["post_snapshot_id"], ["post_snapshots.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("evidence_id", "platform_post_id", name="uq_evidence_post"),
    )
    op.create_index(
        "ix_evidence_item_task_post",
        "circle_page_evidence_items",
        ["circle_task_id", "platform_post_id"],
    )
    op.create_table(
        "screenshot_artifact_groups",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("chain_root_run_id", sa.String(36), nullable=False),
        sa.Column("platform_code", sa.String(32), nullable=False),
        sa.Column("external_id", sa.String(80), nullable=False),
        sa.Column("circle_name", sa.String(200)),
        sa.Column("section", sa.String(32), nullable=False),
        sa.Column("list_order", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.Column("negative_count", sa.Integer(), nullable=False),
        sa.Column("dirty", sa.Boolean(), nullable=False),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "chain_root_run_id",
            "platform_code",
            "external_id",
            "section",
            "list_order",
            name="uq_screenshot_artifact_source",
        ),
    )
    op.create_index(
        "ix_screenshot_artifact_group_status",
        "screenshot_artifact_groups",
        ["status", "updated_at"],
    )
    op.create_table(
        "screenshot_artifact_contributions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("group_id", sa.String(36), nullable=False),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("circle_task_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["screenshot_artifact_groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["extraction_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["circle_task_id"], ["circle_tasks.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("group_id", "circle_task_id", name="uq_group_task"),
    )
    op.create_table(
        "screenshot_artifact_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("group_id", sa.String(36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("reason", sa.String(64), nullable=False),
        sa.Column("input_sha256", sa.String(64), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.Column("negative_count", sa.Integer(), nullable=False),
        sa.Column("tiles", sa.JSON(), nullable=False),
        sa.Column("items", sa.JSON(), nullable=False),
        sa.Column("package_path", sa.Text(), nullable=False),
        sa.Column("package_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("error_message", sa.Text()),
        sa.ForeignKeyConstraint(["group_id"], ["screenshot_artifact_groups.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("group_id", "version", name="uq_screenshot_artifact_version"),
    )


def downgrade() -> None:
    op.drop_table("screenshot_artifact_versions")
    op.drop_table("screenshot_artifact_contributions")
    op.drop_index("ix_screenshot_artifact_group_status", table_name="screenshot_artifact_groups")
    op.drop_table("screenshot_artifact_groups")
    op.drop_index("ix_evidence_item_task_post", table_name="circle_page_evidence_items")
    op.drop_table("circle_page_evidence_items")
    op.drop_index("ix_circle_page_evidence_run", table_name="circle_page_evidence")
    op.drop_table("circle_page_evidence")
