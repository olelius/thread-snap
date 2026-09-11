"""按冻结清单校验卡片坐标；图片颜色、纹理与OCR不参与定位。"""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

BOUND_LIST_SCHEMA = "circle-page-v2-bound-geometry"
LEGACY_DOM_ADAPTERS = {
    "autohome-club-v10-scrapling-page-evidence",
    "autohome-club-v11-scrapling-page-evidence-frame",
    "yiche-community-v10-page-evidence",
    "yiche-community-v11-question-page-evidence",
}
LEGACY_NARROW_ADAPTER = "autohome-club-v10-scrapling-page-evidence"


def _invalid(message: str) -> None:
    raise ValueError(f"页面证据几何不一致：{message}")


def _number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        _invalid("坐标须为有限数值")
    return float(value)


def manifest_rect(rect: dict[str, Any], size: tuple[int, int]) -> tuple[int, int, int, int]:
    """复用既有清单到整数像素的round合同，异常值不夹取为合法矩形。"""

    values = tuple(_number(rect.get(key)) for key in ("x", "y", "width", "height"))
    x, y, width, height = values
    if x < 0 or y < 0 or width <= 0 or height <= 0:
        _invalid("矩形位置或尺寸无效")
    if x + width > size[0] + 1e-6 or y + height > size[1] + 1e-6:
        _invalid("矩形超出原始页面")
    rounded = tuple(round(value) for value in values)
    if rounded[2] < 1 or rounded[3] < 1:
        _invalid("矩形没有有效像素")
    return rounded


def recorded_frame(
    item: Any, size: tuple[int, int], adapter_version: str
) -> tuple[int, int, int, int]:
    """直接使用保存的DOM矩形；仅旧汽车之家窄框使用既有确定性边距公式。"""

    x, y, width, height = manifest_rect(
        {key: getattr(item, key) for key in ("x", "y", "width", "height")}, size
    )
    if adapter_version == LEGACY_NARROW_ADAPTER:
        gutter = max(1, int(width * 0.02 / 0.96))
        x -= gutter
        width += 2 * gutter
    if x < 0 or x + width > size[0] or y + height > size[1]:
        _invalid("适配器坐标转换超出原图")
    return x, y, x + width, y + height


def validate_manifest_geometry(manifest: dict[str, Any], size: tuple[int, int]) -> dict[str, Any]:
    """校验完整页面所有卡片，而非仅检查已经采集成功或判负的条目。"""

    document, viewport = manifest.get("document") or {}, manifest.get("viewport") or {}
    if (document.get("width"), document.get("height")) != size:
        _invalid("PNG尺寸与清单文档尺寸不同")
    if viewport.get("device_scale_factor", 1) != 1:
        _invalid("历史像素坐标只支持已声明的DPR1")
    schema = manifest.get("list_schema_version", "circle-page-v1")
    adapter = str(manifest.get("adapter_version") or "")
    if schema == BOUND_LIST_SCHEMA:
        geometry = manifest.get("capture_geometry") or {}
        digest = geometry.get("before_sha256", "")
        if (
            geometry.get("schema") != "threadsnap.capture-geometry.v1"
            or geometry.get("coordinate_space") != "document-css-px"
            or geometry.get("device_scale_factor") != 1
            or geometry.get("scrollbar_policy") != "native-hidden"
            or geometry.get("layout_viewport")
            != {"width": viewport.get("width"), "height": viewport.get("height")}
            or document.get("width") != viewport.get("width")
            or geometry.get("png_size") != {"width": size[0], "height": size[1]}
            or not isinstance(digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
            or digest != geometry.get("after_sha256")
        ):
            _invalid("缺少截图前后同一几何绑定")
        authority = "bound-dom-png"
    elif schema == "circle-page-v1" and adapter in LEGACY_DOM_ADAPTERS:
        authority = "legacy-recorded-dom"
    else:
        _invalid("该历史适配器尚无明确坐标合同，保留旧成果而不猜测边界")
    rows = manifest.get("rows")
    if not isinstance(rows, list):
        _invalid("原始清单缺少卡片行")
    indexed: dict[str, dict[str, Any]] = {}
    previous_position = -1
    boxes: list[tuple[int, int, int, int]] = []
    for row in rows:
        if not isinstance(row, dict):
            _invalid("原始卡片行格式错误")
        post_id = row.get("post_id")
        position, url = row.get("source_position"), row.get("url")
        if not isinstance(post_id, str) or not post_id or post_id in indexed:
            _invalid("原始帖子身份缺失或重复")
        if (
            isinstance(position, bool)
            or not isinstance(position, int)
            or position <= previous_position
        ):
            _invalid("卡片来源顺序缺失、重复或倒置")
        if not isinstance(url, str) or not url:
            _invalid("原始卡片链接缺失")
        rect = manifest_rect(row.get("rect") or {}, size)
        x, y, width, height = rect
        box = (x, y, x + width, y + height)
        for other in boxes:
            if (
                min(box[2], other[2]) - max(box[0], other[0]) > 1
                and min(box[3], other[3]) - max(box[1], other[1]) > 1
            ):
                _invalid("不同帖子卡片矩形重叠")
        indexed[post_id] = {"row": row, "rect": rect}
        boxes.append(box)
        previous_position = position
    return {"rows": indexed, "authority": authority}


def load_frame_geometry(
    evidence: Any, size: tuple[int, int], cards: list[tuple[int, Any, Any]]
) -> dict[str, Any]:
    """由不可变清单验证数据库/帖子绑定，拒绝正确图片配上另一条帖子的坐标。"""

    path = Path(evidence.manifest_path)
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != evidence.manifest_sha256:
        _invalid("原始清单哈希异常")
    manifest = json.loads(raw)
    for key, expected in (
        ("adapter_version", evidence.adapter_version),
        ("list_schema_version", evidence.list_schema_version),
        ("page_number", evidence.page_number),
        ("exact_url", evidence.exact_url),
    ):
        if manifest.get(key) != expected:
            _invalid(f"清单与数据库的{key}不同")
    if (evidence.document_width, evidence.document_height) != size:
        _invalid("数据库页面尺寸与PNG不同")
    result = validate_manifest_geometry(manifest, size)
    for _index, item, post in cards:
        entry = result["rows"].get(item.platform_post_id)
        if (
            entry is None
            or item.platform_post_id != post.platform_post_id
            or item.post_snapshot_id != post.id
            or item.evidence_id != evidence.id
            or item.circle_task_id != evidence.circle_task_id
            or item.url != entry["row"]["url"]
            or item.source_position != entry["row"]["source_position"]
            or (item.x, item.y, item.width, item.height) != entry["rect"]
            or item.text_sha256
            != hashlib.sha256(str(entry["row"].get("text") or "").encode()).hexdigest()
        ):
            _invalid("帖子ID、清单、数据库坐标或内容身份未绑定到同一张卡片")
    return result
