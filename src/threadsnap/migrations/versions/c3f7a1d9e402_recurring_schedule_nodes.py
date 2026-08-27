"""add recurring schedule nodes

Revision ID: c3f7a1d9e402
Revises: b7d2f4a6c803
Create Date: 2026-08-27
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c3f7a1d9e402"
down_revision: Union[str, Sequence[str], None] = "b7d2f4a6c803"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("schedule_nodes") as batch_op:
        batch_op.add_column(
            sa.Column("node_type", sa.String(length=16), nullable=False, server_default="weekly")
        )
        batch_op.add_column(sa.Column("end_time_of_day", sa.String(length=8), nullable=True))
        batch_op.add_column(sa.Column("interval_minutes", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("schedule_nodes") as batch_op:
        batch_op.drop_column("interval_minutes")
        batch_op.drop_column("end_time_of_day")
        batch_op.drop_column("node_type")
