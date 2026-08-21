"""add independent DeepSeek sentiment connection

Revision ID: c6f1e2a93b47
Revises: ab4d92e7c601
Create Date: 2026-08-21
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c6f1e2a93b47"
down_revision: Union[str, Sequence[str], None] = "ab4d92e7c601"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("sentiment_configs") as batch_op:
        batch_op.add_column(
            sa.Column(
                "deepseek_base_url",
                sa.Text(),
                nullable=False,
                server_default="https://api.deepseek.com",
            )
        )
        batch_op.add_column(sa.Column("deepseek_encrypted_api_key", sa.LargeBinary()))


def downgrade() -> None:
    with op.batch_alter_table("sentiment_configs") as batch_op:
        batch_op.drop_column("deepseek_encrypted_api_key")
        batch_op.drop_column("deepseek_base_url")
