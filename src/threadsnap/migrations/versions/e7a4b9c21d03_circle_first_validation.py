"""circle first validation

Revision ID: e7a4b9c21d03
Revises: c5d1f0a92b34
Create Date: 2026-08-17 20:30:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e7a4b9c21d03"
down_revision: Union[str, Sequence[str], None] = "c5d1f0a92b34"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """记录首次成功验证时间，并保持已有自动参与选择不变。"""

    op.add_column("circles", sa.Column("first_validated_at", sa.DateTime(timezone=True)))
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "UPDATE circles "
            "SET first_validated_at = COALESCE(validated_at, updated_at, created_at) "
            "WHERE validation_status = 'verified'"
        )
    )


def downgrade() -> None:
    """移除首次成功验证时间。"""

    op.drop_column("circles", "first_validated_at")
