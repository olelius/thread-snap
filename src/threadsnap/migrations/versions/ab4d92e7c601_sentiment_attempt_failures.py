"""preserve failed sentiment response attempts

Revision ID: ab4d92e7c601
Revises: f2a9c41d7e30
Create Date: 2026-08-21
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "ab4d92e7c601"
down_revision: Union[str, Sequence[str], None] = "f2a9c41d7e30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("sentiment_analyses") as batch_op:
        batch_op.add_column(
            sa.Column(
                "attempt_failures",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'[]'"),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("sentiment_analyses") as batch_op:
        batch_op.drop_column("attempt_failures")
