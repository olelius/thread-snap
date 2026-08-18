"""circle export key

Revision ID: d4c8a7e91f02
Revises: b73a1d6c42ef
Create Date: 2026-08-18
"""

import secrets
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4c8a7e91f02"
down_revision: Union[str, Sequence[str], None] = "b73a1d6c42ef"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SOURCE_KEY_ALPHABET = "23456789abcdefghjkmnpqrstuvwxyz"


def _new_source_key(used: set[str]) -> str:
    while True:
        value = "".join(secrets.choice(SOURCE_KEY_ALPHABET) for _ in range(10))
        if value not in used:
            used.add(value)
            return value


def upgrade() -> None:
    op.add_column("circles", sa.Column("export_key", sa.String(length=10), nullable=True))
    connection = op.get_bind()
    circle_ids = list(connection.execute(sa.text("SELECT id FROM circles")).scalars())
    used: set[str] = set()
    for circle_id in circle_ids:
        connection.execute(
            sa.text("UPDATE circles SET export_key = :export_key WHERE id = :circle_id"),
            {"export_key": _new_source_key(used), "circle_id": circle_id},
        )
    with op.batch_alter_table("circles") as batch_op:
        batch_op.alter_column(
            "export_key",
            existing_type=sa.String(length=10),
            nullable=False,
        )
        batch_op.create_unique_constraint("uq_circle_export_key", ["export_key"])


def downgrade() -> None:
    with op.batch_alter_table("circles") as batch_op:
        batch_op.drop_constraint("uq_circle_export_key", type_="unique")
        batch_op.drop_column("export_key")
