"""replace retired reputation metric with review article count

Revision ID: a6c9e2f4b701
Revises: d8f4a2b6c901
Create Date: 2026-08-26
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a6c9e2f4b701"
down_revision: Union[str, Sequence[str], None] = "d8f4a2b6c901"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _decode(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _scrub(value: Any) -> Any:
    """递归清除已经退役的口碑指标键，不把旧值映射为新指标。"""

    value = _decode(value)
    if isinstance(value, dict):
        return {
            key: _scrub(item)
            for key, item in value.items()
            if key != "circle_content"
        }
    if isinstance(value, list):
        return [_scrub(item) for item in value]
    return value


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def upgrade() -> None:
    """删除旧指标数据及其派生汇报，正式终态批次等待按新模板重建。"""

    bind = op.get_bind()
    for row in bind.execute(sa.text("SELECT id, metrics FROM reputation_results")):
        cleaned = _scrub(row.metrics)
        if cleaned != _decode(row.metrics):
            bind.execute(
                sa.text("UPDATE reputation_results SET metrics=:metrics WHERE id=:id"),
                {"id": row.id, "metrics": _json_text(cleaned)},
            )

    for row in bind.execute(sa.text("SELECT id, baseline_snapshot FROM reputation_runs")):
        cleaned = _scrub(row.baseline_snapshot)
        if cleaned != _decode(row.baseline_snapshot):
            bind.execute(
                sa.text(
                    "UPDATE reputation_runs SET baseline_snapshot=:snapshot WHERE id=:id"
                ),
                {"id": row.id, "snapshot": _json_text(cleaned)},
            )

    artifacts = list(
        bind.execute(sa.text("SELECT number, report_path, xlsx_path FROM reputation_runs"))
    )
    for row in artifacts:
        for raw_path, suffix in ((row.report_path, ".txt"), (row.xlsx_path, ".xlsx")):
            path = Path(str(raw_path)) if raw_path else None
            if path and path.name == f"{row.number}{suffix}":
                path.unlink(missing_ok=True)

    bind.execute(
        sa.text(
            """
            UPDATE reputation_runs
            SET report_text=NULL,
                report_path=NULL,
                xlsx_path=NULL,
                report_status=CASE
                    WHEN source_type='scheduled'
                     AND status IN ('success','partial_success','failed') THEN 'waiting'
                    ELSE 'not_generated'
                END
            """
        )
    )


def downgrade() -> None:
    """已删除的业务数据与派生产物不从无来源状态反向伪造。"""
