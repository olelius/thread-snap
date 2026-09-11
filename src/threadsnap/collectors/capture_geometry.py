"""把列表 DOM 几何与同一次全页 PNG 绑定，不从图像颜色猜测卡片边界。"""

from __future__ import annotations

import hashlib
import io
import json
import math
from typing import Any

from PIL import Image

from ..browser_runtime import browser_launch_args
from .base import CollectorFailure

LIST_SCHEMA_VERSION = "circle-page-v2-bound-geometry"
GEOMETRY_SCHEMA = "threadsnap.capture-geometry.v1"


def capture_browser_launch_args() -> list[str]:
    """从启动即原生隐藏滚动条，让有界面/无头浏览器与全页捕获保持相同排版宽度。"""

    return [*browser_launch_args(), "--hide-scrollbars"]


def _snapshot_script(rows_script: str) -> str:
    """在一次浏览器求值中读取平台行、文档和媒体，避免拆开读取形成混合状态。"""

    return """els => {
      const rows = (ROWS_SCRIPT)(els);
      const root = document.documentElement;
      const body = document.body;
      return {rows,
        document:{width:Math.max(root.scrollWidth,body?.scrollWidth||0,
          root.offsetWidth,body?.offsetWidth||0,root.clientWidth,body?.clientWidth||0),
          height:Math.max(root.scrollHeight,body?.scrollHeight||0,
          root.offsetHeight,body?.offsetHeight||0,root.clientHeight,body?.clientHeight||0)},
        url:location.href,
        viewport:{width:innerWidth,height:innerHeight,device_scale_factor:devicePixelRatio},
        layout_viewport:{width:root.clientWidth,height:root.clientHeight},
        scroll:{x:scrollX,y:scrollY},
        media:els.flatMap((card,card_index)=>Array.from(card.querySelectorAll('img')).map(img=>{
          const rect=img.getBoundingClientRect();
          const style=getComputedStyle(img);
          return {card_index,src:img.currentSrc||img.src||'',data_src:img.dataset.src||'',
            complete:img.complete,natural_width:img.naturalWidth,natural_height:img.naturalHeight,
            visible:style.display!=='none'&&style.visibility!=='hidden'&&rect.width>0&&rect.height>0,
            rect:{x:rect.x+scrollX,y:rect.y+scrollY,width:rect.width,height:rect.height}};
        }))};
    }""".replace("ROWS_SCRIPT", rows_script)


def _finite_number(value: Any) -> bool:
    """只接受有限数值，避免布尔值、NaN 或无穷大混入截图坐标。"""

    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _validate_snapshot(snapshot: dict[str, Any], page_number: int) -> None:
    """截图前校验完整文档坐标；不裁剪、缩放或修饰无效矩形。"""

    def invalid(reason: str) -> None:
        raise CollectorFailure(
            "PAGE_EVIDENCE_LAYOUT_INVALID", f"圈子第 {page_number} 页几何快照无效：{reason}。"
        )

    document = snapshot.get("document") or {}
    width, height = document.get("width"), document.get("height")
    if not all(_finite_number(value) and value > 0 for value in (width, height)):
        invalid("文档尺寸须为正有限数值")
    viewport = snapshot.get("viewport") or {}
    if viewport.get("device_scale_factor") != 1:
        invalid("设备像素比须为1")
    if not all(
        _finite_number(viewport.get(key)) and viewport[key] > 0 for key in ("width", "height")
    ):
        invalid("视口尺寸无效")
    if (
        snapshot.get("layout_viewport")
        != {"width": viewport["width"], "height": viewport["height"]}
        or width != viewport["width"]
    ):
        # captureBeyondViewport 可在浏览器内部临时去掉经典滚动条；
        # 必须确认原生隐藏已生效且没有横向溢出扩宽，不能只凭两个相等快照推断同宽。
        raise CollectorFailure(
            "PAGE_EVIDENCE_IMAGE_SIZE_MISMATCH",
            f"圈子第 {page_number} 页原生截图视口尚未同宽，等待布局恢复后续作。",
        )
    if snapshot.get("scroll") != {"x": 0, "y": 0}:
        invalid("捕获时页面须位于原始页首")
    if not isinstance(snapshot.get("url"), str) or not snapshot["url"]:
        invalid("页面缺少URL")
    rows = snapshot.get("rows")
    if not isinstance(rows, list):
        invalid("卡片清单格式无效")
    for index, row in enumerate(rows):
        rect = row.get("rect") or {}
        values = [rect.get(key) for key in ("x", "y", "width", "height")]
        if not all(_finite_number(value) for value in values):
            invalid(f"第{index + 1}张卡片含非有限坐标")
        x, y, card_width, card_height = values
        if x < 0 or y < 0 or card_width <= 0 or card_height <= 0:
            invalid(f"第{index + 1}张卡片尺寸或位置无效")
        if x + card_width > width or y + card_height > height:
            invalid(f"第{index + 1}张卡片超出文档")
    for item in snapshot.get("media") or []:
        if item.get("visible") and (
            not item.get("src")
            or not item.get("complete")
            or not item.get("natural_width", 0) > 0
            or not item.get("natural_height", 0) > 0
        ):
            raise CollectorFailure(
                "PAGE_EVIDENCE_MEDIA_INCOMPLETE",
                f"圈子第 {page_number} 页在捕获时仍有未加载完成的可见媒体。",
            )


def _snapshot_sha256(snapshot: dict[str, Any]) -> str:
    """对同次页面身份、文本、媒体及几何整体求摘要，供截图绑定和审计。"""

    return hashlib.sha256(
        json.dumps(
            snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    ).hexdigest()


def capture_bound_screenshot(
    page: Any, cards: Any, rows_script: str, *, page_number: int
) -> dict[str, Any]:
    """最多两次同页捕获；只有截图前后快照及 PNG 尺寸一致才返回可持久化证据。

    参数 rows_script 为平台已有 DOM 行读取函数，不注入 CSS 或改变页面内容。
    返回原始行、文档/视口、PNG 与可写入不可变清单的几何绑定元数据。
    """

    script = _snapshot_script(rows_script)
    for attempt in range(2):
        before = cards.evaluate_all(script)
        _validate_snapshot(before, page_number)
        before_sha256 = _snapshot_sha256(before)
        screenshot = page.screenshot(full_page=True, type="png")
        after = cards.evaluate_all(script)
        _validate_snapshot(after, page_number)
        after_sha256 = _snapshot_sha256(after)
        if before_sha256 != after_sha256:
            if attempt == 0:
                page.wait_for_timeout(250)
                continue
            raise CollectorFailure(
                "PAGE_EVIDENCE_LAYOUT_UNSTABLE",
                f"圈子第 {page_number} 页截图前后身份、内容或几何持续变化，已丢弃未绑定截图。",
            )
        try:
            with Image.open(io.BytesIO(screenshot)) as image:
                if image.format != "PNG":
                    raise ValueError("not a PNG")
                png_size = {"width": image.width, "height": image.height}
                image.verify()
        except Exception as exc:
            raise CollectorFailure(
                "PAGE_EVIDENCE_IMAGE_INVALID", f"圈子第 {page_number} 页截图不是完整 PNG。"
            ) from exc
        if png_size != before["document"]:
            raise CollectorFailure(
                "PAGE_EVIDENCE_IMAGE_SIZE_MISMATCH",
                f"圈子第 {page_number} 页 PNG 尺寸与同次文档坐标系不一致。",
            )
        return {
            "raw_rows": before["rows"],
            "document": before["document"],
            "viewport": before["viewport"],
            "screenshot": screenshot,
            "capture_geometry": {
                "schema": GEOMETRY_SCHEMA,
                "coordinate_space": "document-css-px",
                "device_scale_factor": 1,
                "scrollbar_policy": "native-hidden",
                "layout_viewport": before["layout_viewport"],
                "png_size": png_size,
                "before_sha256": before_sha256,
                "after_sha256": after_sha256,
            },
        }
    raise AssertionError("capture attempt budget exhausted")
