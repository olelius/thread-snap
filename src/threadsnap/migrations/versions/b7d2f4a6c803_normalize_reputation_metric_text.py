"""normalize reputation metric text fields

Revision ID: b7d2f4a6c803
Revises: a6c9e2f4b701
Create Date: 2026-08-26
"""

from __future__ import annotations

import json
from numbers import Number
from typing import Any, Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b7d2f4a6c803"
down_revision: Union[str, Sequence[str], None] = "a6c9e2f4b701"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_METRIC_TEXT_FIELDS = (
    "raw",
    "value",
    "baseline_raw",
    "baseline_value",
    "delta",
)


def _decode_container(value: Any) -> Any:
    """只解码数据库JSON容器，避免再次解析容器内部的字符串叶子。"""

    if isinstance(value, str):
        return json.loads(value)
    return value


def _metric_text(value: Any) -> Any:
    """把曾被错误JSON解析的指标数字恢复为前端合同要求的文本。"""

    if value is None or isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Number):
        return str(value)
    return value


def _normalize_metrics(metrics: Any) -> tuple[Any, bool]:
    """修复指标文本字段，同时保留计数、方向和来源等字段原类型。"""

    if not isinstance(metrics, dict):
        return metrics, False
    changed = False
    for metric in metrics.values():
        if not isinstance(metric, dict):
            continue
        for field in _METRIC_TEXT_FIELDS:
            if field not in metric:
                continue
            normalized = _metric_text(metric[field])
            if normalized != metric[field] or type(normalized) is not type(metric[field]):
                metric[field] = normalized
                changed = True
    return metrics, changed


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def upgrade() -> None:
    """恢复既有结果和冻结基线中的口碑指标文本类型。"""

    bind = op.get_bind()
    for row in bind.execute(sa.text("SELECT id, metrics FROM reputation_results")):
        metrics, changed = _normalize_metrics(_decode_container(row.metrics))
        if changed:
            bind.execute(
                sa.text("UPDATE reputation_results SET metrics=:metrics WHERE id=:id"),
                {"id": row.id, "metrics": _json_text(metrics)},
            )

    for row in bind.execute(sa.text("SELECT id, baseline_snapshot FROM reputation_runs")):
        snapshot = _decode_container(row.baseline_snapshot)
        if not isinstance(snapshot, dict):
            continue
        changed = False
        for baseline in snapshot.values():
            if not isinstance(baseline, dict):
                continue
            _, metrics_changed = _normalize_metrics(baseline.get("metrics"))
            changed = changed or metrics_changed
        if changed:
            bind.execute(
                sa.text(
                    "UPDATE reputation_runs SET baseline_snapshot=:snapshot WHERE id=:id"
                ),
                {"id": row.id, "snapshot": _json_text(snapshot)},
            )


def downgrade() -> None:
    """文本到数字的错误转换不可逆，因此降级不重新制造错误类型。"""
