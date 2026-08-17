"""schedule nodes select multiple rules

Revision ID: a91c4e7d2f10
Revises: e7a4b9c21d03
Create Date: 2026-08-17 23:40:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a91c4e7d2f10"
down_revision: Union[str, Sequence[str], None] = "e7a4b9c21d03"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """迁移节点单规则引用，并记录批次的全部规则版本快照。"""

    op.create_table(
        "schedule_node_rules",
        sa.Column("schedule_node_id", sa.String(length=36), nullable=False),
        sa.Column("rule_id", sa.String(length=36), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["rule_id"], ["extraction_rules.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["schedule_node_id"], ["schedule_nodes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("schedule_node_id", "rule_id"),
        sa.UniqueConstraint(
            "schedule_node_id", "position", name="uq_schedule_node_rule_position"
        ),
    )
    op.execute(
        sa.text(
            "INSERT INTO schedule_node_rules (schedule_node_id, rule_id, position) "
            "SELECT id, rule_id, 0 FROM schedule_nodes"
        )
    )
    op.create_table(
        "extraction_run_rules",
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("rule_id", sa.String(length=36), nullable=False),
        sa.Column("rule_version", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["rule_id"], ["extraction_rules.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["run_id"], ["extraction_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("run_id", "rule_id"),
        sa.UniqueConstraint("run_id", "position", name="uq_extraction_run_rule_position"),
    )
    op.execute(
        sa.text(
            "INSERT INTO extraction_run_rules (run_id, rule_id, rule_version, position) "
            "SELECT id, extraction_rule_id, extraction_rule_version, 0 "
            "FROM extraction_runs "
            "WHERE extraction_rule_id IS NOT NULL AND extraction_rule_version IS NOT NULL"
        )
    )
    op.add_column(
        "schedule_events",
        sa.Column(
            "rule_snapshots",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )


def downgrade() -> None:
    """移除多规则关联，保留原表中的首条兼容规则引用。"""

    op.drop_column("schedule_events", "rule_snapshots")
    op.drop_table("extraction_run_rules")
    op.drop_table("schedule_node_rules")
