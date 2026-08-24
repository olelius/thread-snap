"""add sentiment cloud concurrency

Revision ID: d4e8f6a1b203
Revises: a2d7e9f103bc
Create Date: 2026-08-24
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d4e8f6a1b203"
down_revision: Union[str, Sequence[str], None] = "a2d7e9f103bc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("sentiment_configs") as batch_op:
        batch_op.add_column(
            sa.Column("cloud_concurrency", sa.Integer(), nullable=False, server_default="8")
        )


def downgrade() -> None:
    with op.batch_alter_table("sentiment_configs") as batch_op:
        batch_op.drop_column("cloud_concurrency")
