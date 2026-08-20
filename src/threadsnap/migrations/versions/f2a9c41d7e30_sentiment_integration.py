"""sentiment integration

Revision ID: f2a9c41d7e30
Revises: d4c8a7e91f02
Create Date: 2026-08-20
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f2a9c41d7e30"
down_revision: Union[str, Sequence[str], None] = "d4c8a7e91f02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEFAULT_PRODUCTS = [
    "A9", "A9L", "QQ3 EV", "T9L", "T11", "T9", "艾瑞泽8", "艾瑞泽8PRO",
    "瑞虎8", "瑞虎8PLUS", "瑞虎8PRO", "瑞虎9", "瑞虎7L", "风云T7",
]


def upgrade() -> None:
    with op.batch_alter_table("post_snapshots") as batch_op:
        batch_op.add_column(sa.Column("analysis_status", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("sentiment_result", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("sentiment_source", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("sentiment_updated_at", sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        "sentiment_configs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=False),
        sa.Column("encrypted_api_key", sa.LargeBinary(), nullable=True),
        sa.Column("model_code", sa.String(length=120), nullable=False),
        sa.Column("validation_status", sa.String(length=32), nullable=False),
        sa.Column("validation_error", sa.Text(), nullable=True),
        sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("subject_version", sa.Integer(), nullable=False),
        sa.Column("brand", sa.String(length=120), nullable=False),
        sa.Column("products", sa.JSON(), nullable=False),
        sa.Column("supplement", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        sa.text(
            "INSERT INTO sentiment_configs "
            "(id, revision, enabled, base_url, encrypted_api_key, model_code, validation_status, "
            "subject_version, brand, products, created_at, updated_at) "
            "VALUES (1, 1, 0, '', NULL, 'qwen3.5-omni-plus-2026-03-15', 'unverified', "
            "1, '奇瑞', :products, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ).bindparams(products=sa.JSON().bind_processor(op.get_bind().dialect)(DEFAULT_PRODUCTS))
    )
    op.create_table(
        "sentiment_analyses",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("post_id", sa.String(length=36), nullable=False),
        sa.Column("platform_code", sa.String(length=32), nullable=False),
        sa.Column("platform_post_id", sa.String(length=80), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("config_revision", sa.Integer(), nullable=False),
        sa.Column("subject_version", sa.Integer(), nullable=False),
        sa.Column("subject_snapshot", sa.JSON(), nullable=False),
        sa.Column("model_code", sa.String(length=120), nullable=False),
        sa.Column("prompt_version", sa.String(length=32), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("result", sa.String(length=32), nullable=True),
        sa.Column("matched_subjects", sa.JSON(), nullable=False),
        sa.Column("primary_category", sa.String(length=64), nullable=True),
        sa.Column("secondary_categories", sa.JSON(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("modalities", sa.JSON(), nullable=True),
        sa.Column("raw_response", sa.Text(), nullable=True),
        sa.Column("locally_recovered", sa.Boolean(), nullable=False),
        sa.Column("provider_request_id", sa.String(length=200), nullable=True),
        sa.Column("usage", sa.JSON(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("reused_from_analysis_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["post_id"], ["post_snapshots.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reused_from_analysis_id"], ["sentiment_analyses.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("post_id", name="uq_sentiment_analysis_post"),
    )
    op.create_index("ix_sentiment_analysis_queue", "sentiment_analyses", ["status", "created_at"])
    op.create_index("ix_sentiment_analysis_identity", "sentiment_analyses", ["platform_code", "platform_post_id", "input_hash"])
    op.create_table(
        "manual_sentiment_revisions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("post_id", sa.String(length=36), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("result", sa.String(length=32), nullable=True),
        sa.Column("primary_category", sa.String(length=64), nullable=True),
        sa.Column("secondary_categories", sa.JSON(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("inherited_from_revision_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["post_id"], ["post_snapshots.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["inherited_from_revision_id"], ["manual_sentiment_revisions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_manual_sentiment_post_created", "manual_sentiment_revisions", ["post_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_manual_sentiment_post_created", table_name="manual_sentiment_revisions")
    op.drop_table("manual_sentiment_revisions")
    op.drop_index("ix_sentiment_analysis_identity", table_name="sentiment_analyses")
    op.drop_index("ix_sentiment_analysis_queue", table_name="sentiment_analyses")
    op.drop_table("sentiment_analyses")
    op.drop_table("sentiment_configs")
    with op.batch_alter_table("post_snapshots") as batch_op:
        batch_op.drop_column("sentiment_updated_at")
        batch_op.drop_column("sentiment_source")
        batch_op.drop_column("sentiment_result")
        batch_op.drop_column("analysis_status")
