"""模板新增业务字段的只读投影与完整截图引用，不改变旧字段语义。"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .collectors.registry import get_platform_spec
from .models import (
    CircleTask,
    ExtractionRun,
    PostSnapshot,
    ScreenshotArtifactContribution,
    ScreenshotArtifactGroup,
    ScreenshotArtifactVersion,
)
from .sentiment import SentimentService
from .table_export import ANALYSIS_NAMES, SENTIMENT_NAMES, SOURCE_NAMES

EXTRA_FIELDS = {
    "platform.code": ("text", "来源所属平台代码，适用于全部平台"),
    "platform.name": ("text", "来源所属平台中文名称"),
    "run.number": ("text", "该帖子实际所属的采集批次编号"),
    "run.trigger_type": ("text", "该采集批次的触发类型"),
    "run.created_at": ("datetime", "该采集批次创建时间"),
    "post.collected_at": ("datetime", "帖子快照保存时间"),
    "post.is_deleted": ("boolean", "是否为平台明确删除的帖子"),
    "post.visibility_name": ("text", "中文可见状态，明确删除时显示删除"),
    "sentiment.analysis_status": ("text", "当前分析状态代码"),
    "sentiment.analysis_status_name": ("text", "当前分析状态中文名称"),
    "sentiment.result": ("text", "当前有效舆情结果代码，人工判定优先"),
    "sentiment.result_name": ("text", "当前有效舆情结果：负面、非负面或不相关"),
    "sentiment.source": ("text", "当前有效判定来源代码"),
    "sentiment.source_name": ("text", "判定来源：AI、人工或继承人工"),
    "sentiment.updated_at": ("datetime", "当前有效舆情结果更新时间"),
    "sentiment.summary": ("text", "已保存的 AI 中文总结，不冒充人工结论"),
    "sentiment.matched_subjects": ("collection", "AI 命中的判定对象"),
    "sentiment.primary_category": ("text", "当前有效主要分类代码，人工分类优先"),
    "sentiment.secondary_categories": ("collection", "当前有效次要分类代码，人工分类优先"),
    "sentiment.manual_note": ("text", "当前生效的人工判定说明"),
    "sentiment.model_code": ("text", "已保存分析任务使用的模型"),
    "sentiment.account_name": ("text", "已保存分析任务使用的 AI 账户名称，不含凭证"),
    "sentiment.duration_ms": ("number", "已保存分析任务耗时（毫秒）"),
    "sentiment.error_message": ("text", "已保存的分析失败原因"),
    "sentiment.text_evidence": ("collection", "已保存的文字分析依据"),
    "sentiment.image_evidence": ("collection", "按输入图片编号列出的分析依据"),
    "sentiment.video_visual_evidence": ("collection", "按输入视频编号列出的画面依据"),
    "sentiment.video_audio_evidence": ("collection", "按输入视频编号列出的音频依据"),
    "source.screenshot": ("image", "本来源带负面框选的完整页面截图（PNG）；窄列单行等比显示，每页独立嵌入原图，只放一次，不压缩、裁剪或拼接"),
}


def extra_post_values(db: Session, post: PostSnapshot, task: CircleTask) -> dict[str, Any]:
    """复用页面有效舆情视图；删除帖不导出旧 AI/人工结论。"""
    run = db.get(ExtractionRun, post.run_id)
    detail = {} if post.is_deleted else SentimentService.detail_dict(db, post)
    source = detail.get("source")
    manual = next(
        (item for item in detail.get("manual_history", []) if item["action"] == "set_result"), {},
    ) if source in {"manual", "inherited_manual"} else {}
    values = {
        "platform.code": task.platform_code,
        "platform.name": get_platform_spec(task.platform_code).display_name,
        "run.number": run.number if run else None,
        "run.trigger_type": run.trigger_type if run else None,
        "run.created_at": run.created_at if run else None,
        "post.collected_at": post.created_at,
        "post.is_deleted": post.is_deleted,
        "post.visibility_name": "删除" if post.is_deleted else {"visible": "可见", "hidden": "不可见", "unknown": "未知"}.get(post.visibility),
        "sentiment.analysis_status": post.analysis_status,
        "sentiment.analysis_status_name": "已跳过（帖子已删除）" if post.is_deleted else ANALYSIS_NAMES.get(post.analysis_status),
        "sentiment.result": detail.get("result"),
        "sentiment.result_name": SENTIMENT_NAMES.get(detail.get("result")),
        "sentiment.source": source,
        "sentiment.source_name": SOURCE_NAMES.get(source),
        "sentiment.updated_at": detail.get("updated_at"),
        "sentiment.manual_note": manual.get("note"),
    }
    for key in ("summary", "matched_subjects", "primary_category", "secondary_categories", "model_code", "account_name", "duration_ms", "error_message"):
        values[f"sentiment.{key}"] = detail.get(key)
    modalities = detail.get("modalities") or {}
    values["sentiment.text_evidence"] = (modalities.get("text") or {}).get("evidence", [])
    for kind in ("image", "video_visual", "video_audio"):
        values[f"sentiment.{kind}_evidence"] = [
            f"{int(item['input_index']) + 1}：{evidence}"
            for item in (modalities.get(kind) or {}).get("items", [])
            for evidence in item.get("evidence", [])
        ]
    return values


def source_screenshots(db: Session, tasks: list[CircleTask]) -> list[dict[str, Any]]:
    """按贡献任务定位当前成果，只引用带有效负面框的整页，保留缺失原因。"""
    groups = db.scalars(
        select(ScreenshotArtifactGroup).join(ScreenshotArtifactContribution)
        .where(ScreenshotArtifactContribution.circle_task_id.in_([task.id for task in tasks]))
        .order_by(ScreenshotArtifactGroup.created_at, ScreenshotArtifactGroup.id)
    ).unique().all()
    if not groups:
        return [{"message": "该来源未采集页面截图"}]
    images = []
    for group in groups:
        identity = {"group_id": group.id, "version": group.current_version}
        if group.dirty or group.status not in {"ready", "empty"}:
            images.append({**identity, "message": "截图成果尚未就绪，请完成生成后重新导出"})
            continue
        version = db.scalar(select(ScreenshotArtifactVersion).where(
            ScreenshotArtifactVersion.group_id == group.id,
            ScreenshotArtifactVersion.version == group.current_version,
        ))
        if not version or version.status != "ready":
            images.append({**identity, "message": "截图成果版本缺失"})
            continue
        negative_tiles = {int(item["tile_index"]) for item in version.items if item.get("sentiment_result") == "negative"}
        if not negative_tiles:
            images.append({**identity, "message": "该来源没有负面框选截图"})
            continue
        available_tiles = {int(tile["index"]) for tile in version.tiles}
        if negative_tiles - available_tiles:
            images.append({**identity, "message": "截图分页清单缺失"})
        for tile in sorted(version.tiles, key=lambda item: int(item["index"])):
            if int(tile["index"]) not in negative_tiles:
                continue
            image = {**identity, "index": tile["index"], "sha256": tile["sha256"]}
            path = Path(tile["path"])
            if not path.is_file():
                image["message"] = "截图文件缺失"
            elif hashlib.sha256(path.read_bytes()).hexdigest() != tile["sha256"]:
                image["message"] = "截图文件校验失败"
            else:
                image["path"] = str(path)
            images.append(image)
    return images
