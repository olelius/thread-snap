"""add per-rule AI analysis and screenshot switches

Revision ID: d8f4a2b6c901
Revises: c7e3a1d9b402
Create Date: 2026-08-26
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d8f4a2b6c901"
down_revision: Union[str, Sequence[str], None] = "c7e3a1d9b402"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """既有规则沿用此前默认执行 AI 分析和页面截图的行为。"""

    with op.batch_alter_table("extraction_rule_versions") as batch:
        batch.add_column(
            sa.Column(
                "ai_analysis_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            )
        )
        batch.add_column(
            sa.Column(
                "screenshot_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("extraction_rule_versions") as batch:
        batch.drop_column("screenshot_enabled")
        batch.drop_column("ai_analysis_enabled")
