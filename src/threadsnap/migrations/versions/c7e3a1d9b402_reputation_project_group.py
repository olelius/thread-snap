"""backfill reputation vehicle project groups

Revision ID: c7e3a1d9b402
Revises: b4f9d2e6a701
Create Date: 2026-08-25
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c7e3a1d9b402"
down_revision: Union[str, Sequence[str], None] = "b4f9d2e6a701"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEFAULT_PROJECT_GROUP = "奇瑞项目组"


def _drafts() -> sa.Table:
    return sa.table(
        "reputation_scope_drafts",
        sa.column("id", sa.String()),
        sa.column("revision", sa.Integer()),
        sa.column("data", sa.JSON()),
    )


def upgrade() -> None:
    """只补齐当前可编辑草稿；已发布版本继续保持不可变。"""

    drafts = _drafts()
    connection = op.get_bind()
    for row in connection.execute(sa.select(drafts.c.id, drafts.c.revision, drafts.c.data)).mappings():
        data = dict(row["data"] or {})
        vehicles = [dict(vehicle) for vehicle in data.get("vehicles", [])]
        changed = False
        for vehicle in vehicles:
            if not str(vehicle.get("project_group") or "").strip():
                vehicle["project_group"] = DEFAULT_PROJECT_GROUP
                changed = True
        if changed:
            data["vehicles"] = vehicles
            connection.execute(
                sa.update(drafts)
                .where(drafts.c.id == row["id"])
                .values(data=data, revision=int(row["revision"] or 0) + 1)
            )


def downgrade() -> None:
    """移除草稿中的项目组字段，仍不改写任何已发布版本。"""

    drafts = _drafts()
    connection = op.get_bind()
    for row in connection.execute(sa.select(drafts.c.id, drafts.c.revision, drafts.c.data)).mappings():
        data = dict(row["data"] or {})
        vehicles = [dict(vehicle) for vehicle in data.get("vehicles", [])]
        changed = False
        for vehicle in vehicles:
            if "project_group" in vehicle:
                vehicle.pop("project_group")
                changed = True
        if changed:
            data["vehicles"] = vehicles
            connection.execute(
                sa.update(drafts)
                .where(drafts.c.id == row["id"])
                .values(data=data, revision=int(row["revision"] or 0) + 1)
            )
