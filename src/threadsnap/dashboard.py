"""首页只读聚合：不分页截断统计，不把提取、循环和巡检合并为同一种批次。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request
from sqlalchemy import case, func, select

from .models import ExtractionRun, ReputationRun

router = APIRouter(prefix="/api/v1", tags=["dashboard"])
ACTIVE_STATUSES = ("queued", "running", "waiting_for_auth")
ATTENTION_STATUSES = ("waiting_for_auth", "partial_success", "failed")
RECENT_LIMIT = 8


def build_dashboard(factory, timezone_name: str, now: datetime | None = None) -> dict[str, Any]:
    """返回全量现存批次统计及每类最多8个近期/3个待关注摘要。

    提取/循环的“今日”按创建时间；巡检按计划日期，排除补跑与合成测试。
    只选公开摘要字段，不返回配置快照、凭证、文件路径或报告正文。
    """
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("首页聚合需要带时区的当前时间")
    local = current.astimezone(ZoneInfo(timezone_name))
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    categories = []
    with factory() as db:
        for key, label, model, scope in (
            (
                "extraction",
                "提取批次",
                ExtractionRun,
                ExtractionRun.trigger_type.in_(["manual", "scheduled"]),
            ),
            ("recurring", "循环批次", ExtractionRun, ExtractionRun.trigger_type == "recurring"),
            (
                "reputation",
                "口碑巡检",
                ReputationRun,
                ReputationRun.source_type.in_(["scheduled", "real_acceptance"]),
            ),
        ):
            is_reputation = key == "reputation"
            today = (
                model.planned_date == start.date().isoformat()
                if is_reputation
                else (
                    (model.created_at >= start.astimezone(timezone.utc))
                    & (model.created_at < end.astimezone(timezone.utc))
                )
            )
            counts = (
                db.execute(
                    select(
                        func.count(model.id).label("total"),
                        func.coalesce(func.sum(case((today, 1), else_=0)), 0).label("today"),
                        func.coalesce(
                            func.sum(case((model.status.in_(ACTIVE_STATUSES), 1), else_=0)), 0
                        ).label("active"),
                        func.coalesce(
                            func.sum(case((model.status.in_(ATTENTION_STATUSES), 1), else_=0)), 0
                        ).label("attention"),
                    ).where(scope)
                )
                .mappings()
                .one()
            )
            fields = [
                model.id,
                model.number,
                model.status,
                model.planned_count,
                model.completed_count,
                model.failed_count,
                model.created_at,
                model.finished_at,
            ]
            if is_reputation:
                fields.extend([model.planned_date, model.source_type])
            else:
                fields.append(model.trigger_type)
            order = [model.planned_date.desc()] if is_reputation else []
            order.extend([model.created_at.desc(), model.id.desc()])
            statement = select(*fields).where(scope).order_by(*order)
            recent = [dict(row) for row in db.execute(statement.limit(RECENT_LIMIT)).mappings()]
            attention = [
                dict(row)
                for row in db.execute(
                    statement.where(model.status.in_(ATTENTION_STATUSES)).limit(3)
                ).mappings()
            ]
            categories.append(
                {
                    "key": key,
                    "label": label,
                    **dict(counts),
                    "today_basis": "planned_date" if is_reputation else "created_at",
                    "recent": recent,
                    "attention_items": attention,
                }
            )
    return {
        "generated_at": current,
        "timezone": timezone_name,
        "date": start.date().isoformat(),
        "categories": categories,
    }


@router.get("/dashboard")
def get_dashboard(request: Request) -> dict[str, Any]:
    """复用现有应用容器，不引入另一个数据库或后台任务。"""
    container = request.app.state.container
    return build_dashboard(container.sessions, container.settings.timezone)
