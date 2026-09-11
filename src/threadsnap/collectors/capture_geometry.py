"""把列表 DOM 几何与同一次全页 PNG 绑定，不从图像颜色猜测卡片边界。"""

from __future__ import annotations

import io
from typing import Any

from PIL import Image

from ..browser_runtime import browser_launch_args
from .base import CollectorFailure

LIST_SCHEMA_VERSION = "circle-page-v1"


def capture_browser_launch_args() -> list[str]:
    """从启动即原生隐藏滚动条，让有界面/无头浏览器与全页捕获保持相同排版宽度。"""

    return [*browser_launch_args(), "--hide-scrollbars"]


def _snapshot_script(rows_script: str) -> str:
    """在一次浏览器求值中读取平台行和文档，避免拆开读取形成混合状态。"""

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
        scroll:{x:scrollX,y:scrollY}};
    }""".replace("ROWS_SCRIPT", rows_script)


def capture_bound_screenshot(
    page: Any, cards: Any, rows_script: str, *, page_number: int
) -> dict[str, Any]:
    """最多两次同页捕获；只有截图前后快照及 PNG 尺寸一致才返回可持久化证据。

    参数 rows_script 为平台已有 DOM 行读取函数，不注入 CSS 或改变页面内容。
    媒体和帖子身份沿用平台原有检查；原样返回行、坐标与 PNG，不新增证书校验。
    """

    script = _snapshot_script(rows_script)
    for attempt in range(2):
        before = cards.evaluate_all(script)
        # CDP full-page 内部可能去掉经典滚动条占位；启动即同宽解决根因，
        # 这里只确认策略生效，不重判媒体、业务身份或修改坐标。
        if not (
            before["document"]["width"]
            == before["viewport"]["width"]
            == before["layout_viewport"]["width"]
        ):
            raise CollectorFailure(
                "PAGE_EVIDENCE_IMAGE_SIZE_MISMATCH",
                f"圈子第 {page_number} 页截图排版宽度尚未稳定，稍后自动续作。",
            )
        screenshot = page.screenshot(full_page=True, type="png")
        after = cards.evaluate_all(script)
        if before != after:
            if attempt == 0:
                page.wait_for_timeout(250)
                continue
            raise CollectorFailure(
                "PAGE_EVIDENCE_LAYOUT_UNSTABLE",
                f"圈子第 {page_number} 页截图前后身份、内容或几何持续变化，已丢弃未绑定截图。",
            )
        with Image.open(io.BytesIO(screenshot)) as image:
            png_size = {"width": image.width, "height": image.height}
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
            "capture_geometry": {"scrollbar_policy": "native-hidden", "png_size": png_size},
        }
    raise AssertionError("capture attempt budget exhausted")
