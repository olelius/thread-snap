"""circle list order

Revision ID: b73a1d6c42ef
Revises: a91c4e7d2f10
Create Date: 2026-08-18
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b73a1d6c42ef"
down_revision: Union[str, Sequence[str], None] = "a91c4e7d2f10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("circles") as batch_op:
        batch_op.add_column(
            sa.Column(
                "list_order",
                sa.String(length=32),
                server_default="latest_reply",
                nullable=False,
            )
        )
        batch_op.drop_constraint("uq_circle_platform_external", type_="unique")
        batch_op.create_unique_constraint(
            "uq_circle_platform_source",
            ["platform_code", "external_id", "section", "list_order"],
        )
    with op.batch_alter_table("circle_tasks") as batch_op:
        batch_op.add_column(
            sa.Column(
                "list_order",
                sa.String(length=32),
                server_default="latest_reply",
                nullable=False,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("circle_tasks") as batch_op:
        batch_op.drop_column("list_order")
    with op.batch_alter_table("circles") as batch_op:
        batch_op.drop_constraint("uq_circle_platform_source", type_="unique")
        batch_op.create_unique_constraint(
            "uq_circle_platform_external", ["platform_code", "external_id"]
        )
        batch_op.drop_column("list_order")
