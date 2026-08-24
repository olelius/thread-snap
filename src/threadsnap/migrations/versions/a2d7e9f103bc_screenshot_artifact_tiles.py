"""normalize screenshot artifact tiles and items

Revision ID: a2d7e9f103bc
Revises: f8b6c2d4e901
Create Date: 2026-08-23
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a2d7e9f103bc"
down_revision: Union[str, Sequence[str], None] = "f8b6c2d4e901"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("circle_page_evidence") as batch_op:
        batch_op.add_column(
            sa.Column("browser_version", sa.String(80), nullable=False, server_default="unknown")
        )
        batch_op.add_column(
            sa.Column(
                "list_schema_version",
                sa.String(32),
                nullable=False,
                server_default="circle-page-v1",
            )
        )
        batch_op.add_column(
            sa.Column("device_scale_factor", sa.Integer(), nullable=False, server_default="1")
        )
    op.create_table(
        "screenshot_artifact_tiles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("version_id", sa.String(36), nullable=False),
        sa.Column("tile_index", sa.Integer(), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("file_sha256", sa.String(64), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["version_id"], ["screenshot_artifact_versions.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("version_id", "tile_index", name="uq_version_tile"),
    )
    op.create_table(
        "screenshot_artifact_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("version_id", sa.String(36), nullable=False),
        sa.Column("post_snapshot_id", sa.String(36)),
        sa.Column("platform_post_id", sa.String(80), nullable=False),
        sa.Column("title", sa.Text()),
        sa.Column("sentiment_result", sa.String(32), nullable=False),
        sa.Column("contribution_run_number", sa.String(32), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tile_index", sa.Integer(), nullable=False),
        sa.Column("y", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["version_id"], ["screenshot_artifact_versions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["post_snapshot_id"], ["post_snapshots.id"], ondelete="SET NULL"),
        sa.UniqueConstraint(
            "version_id", "platform_post_id", name="uq_version_artifact_post"
        ),
    )


def downgrade() -> None:
    op.drop_table("screenshot_artifact_items")
    op.drop_table("screenshot_artifact_tiles")
    with op.batch_alter_table("circle_page_evidence") as batch_op:
        batch_op.drop_column("device_scale_factor")
        batch_op.drop_column("list_schema_version")
        batch_op.drop_column("browser_version")
