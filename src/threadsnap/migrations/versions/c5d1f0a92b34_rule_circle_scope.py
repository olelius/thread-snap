"""rule circle scope

Revision ID: c5d1f0a92b34
Revises: 8d3806d229c1
Create Date: 2026-08-17 18:30:00.000000

"""

from __future__ import annotations

import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c5d1f0a92b34"
down_revision: Union[str, Sequence[str], None] = "8d3806d229c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """为不可变规则版本增加明确的圈子范围，并保留旧规则当前行为。"""

    op.add_column(
        "extraction_rule_versions",
        sa.Column(
            "selected_circle_ids",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )
    connection = op.get_bind()
    circle_ids = list(
        connection.execute(
            sa.text(
                "SELECT id FROM circles "
                "WHERE source_kind = 'configured' AND auto_enabled = 1 "
                "ORDER BY created_at, id"
            )
        ).scalars()
    )
    connection.execute(
        sa.text("UPDATE extraction_rule_versions SET selected_circle_ids = :selected_circle_ids"),
        {"selected_circle_ids": json.dumps(circle_ids, ensure_ascii=False)},
    )


def downgrade() -> None:
    """移除规则版本的圈子范围。"""

    op.drop_column("extraction_rule_versions", "selected_circle_ids")
