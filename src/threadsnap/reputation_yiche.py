"""易车车型点评页真实指标与区域截图适配器。"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from time import monotonic
from urllib.parse import quote, urlsplit

from .reputation_adapter import (
    ReputationAdapterError,
    ReputationMappingTarget,
    ReputationPageResult,
)
from .reputation_browser import BrowserReputationAdapter, capture_region, elapsed_ms, stable_measure

ADAPTER_VERSION = "yiche-reputation-v1"
VALIDATION_CONTRACT_VERSION = "yiche-reputation-mapping-v1"
VIEWPORT = {"width": 1440, "height": 1000}
SERIES_URL_RE = re.compile(
    r"^https://(?:car|dianping)\.yiche\.com/(?P<slug>[a-zA-Z0-9_-]+)/(?:koubei/?)?(?:\?.*)?$"
)


def normalize_series_url(url: str, expected_id: str | None = None) -> str:
    """规范为易车点评口碑页；数值ID在真实页面接口门禁中核对。"""

    del expected_id
    value = url.strip()
    match = SERIES_URL_RE.match(value)
    if not match:
        raise ReputationAdapterError(
            "REPUTATION_URL_INVALID", "页面URL必须是易车车型或点评口碑页。"
        )
    return f"https://dianping.yiche.com/{match.group('slug')}/koubei/"


def _api_url(path: str, params: dict[str, object]) -> str:
    return f"https://mapi.yiche.com/{path}?cid=508&param={quote(json.dumps(params, separators=(',', ':')))}"


class YicheReputationAdapter(BrowserReputationAdapter):
    """从易车点评页与同源接口读取五指标并冻结区域证据。"""

    code = "yiche"
    display_name = "易车"
    adapter_version = ADAPTER_VERSION
    validation_contract_version = VALIDATION_CONTRACT_VERSION
    viewport = VIEWPORT

    async def _visit(self, browser, target: ReputationMappingTarget, output_dir: Path):
        started = monotonic()
        context = await browser.new_context(storage_state=self.storage_state, viewport=VIEWPORT)
        page = await context.new_page()
        page.set_default_timeout(self.timeout_seconds * 1000)
        try:
            captured: dict[str, dict] = {}
            response_tasks: list[asyncio.Task] = []

            async def capture(response) -> None:
                if "/point_comment/tags?" in response.url and response.status == 200:
                    captured["tags"] = await response.json()
                elif "/point_comment/query_comment_page_list?" in response.url and response.status == 200:
                    captured["list"] = await response.json()

            page.on("response", lambda response: response_tasks.append(asyncio.create_task(capture(response))))
            expected_url = normalize_series_url(target.platform_url, target.platform_vehicle_id)
            response = await page.goto(expected_url, wait_until="domcontentloaded")
            if response is None or response.status >= 400:
                raise ReputationAdapterError(
                    "REPUTATION_PAGE_UNAVAILABLE", "易车点评页访问异常。", retryable=True
                )
            await page.wait_for_selector(".middle-nav-box .container")
            list_url = _api_url(
                "information_api/api/v1/point_comment/query_comment_page_list",
                {"tagId": "-10", "currentPage": "1", "serialId": target.platform_vehicle_id, "pageSize": 20},
            )
            for _ in range(40):
                if "tags" in captured and "list" in captured:
                    break
                await page.wait_for_timeout(250)
            if response_tasks:
                await asyncio.gather(*response_tasks, return_exceptions=True)
            if "tags" not in captured or "list" not in captured:
                raise ReputationAdapterError(
                    "REPUTATION_METRICS_MISSING", "易车点评指标接口访问异常。", retryable=True
                )
            tags_payload, list_payload = captured["tags"], captured["list"]
            info = ((tags_payload or {}).get("data") or {}).get("pointCommontInfo") or {}
            listing = (list_payload or {}).get("data") or {}
            if str(info.get("serialId") or "") != target.platform_vehicle_id:
                raise ReputationAdapterError(
                    "REPUTATION_IDENTITY_MISMATCH", "易车页面车系ID与冻结映射不一致。"
                )
            script = """
            () => {
              const identity = document.querySelector('.middle-nav-box .container');
              const metrics = document.querySelector('.cm-taglist-box');
              const title = document.querySelector('#commentBrand');
              const score = document.querySelector('.cm-list-score-val');
              const volume = document.querySelector('.cm-list-count');
              const rank = document.querySelector('.brand-rank');
              if (!identity || !title) return null;
              const boxes = [identity, metrics].filter(Boolean).map((node) => node.getBoundingClientRect());
              const left = Math.max(0, Math.min(...boxes.map((box) => box.left)) - 20);
              const top = Math.max(0, Math.min(...boxes.map((box) => box.top + scrollY)) - 4);
              const right = Math.max(...boxes.map((box) => box.right)) + 20;
              const bottom = Math.max(...boxes.map((box) => box.bottom + scrollY)) + 36;
              return {
                actual_name: title.textContent.replace(/点评/g, '').trim(),
                score: score ? (score.textContent.match(/[0-9.]+/) || [])[0] || null : null,
                rank: rank ? (rank.textContent.match(/第\s*(\d+)\s*名/) || [])[1] || null : null,
                rank_scope: rank ? rank.textContent.replace(/第\s*\d+\s*名.*/, '').trim() : '同级车型指数排行',
                volume: volume ? (volume.textContent.match(/[0-9,]+/) || [])[0] || null : null,
                rect: {x: left, y: top, width: right-left, height: bottom-top},
                document_width: document.documentElement.scrollWidth,
                document_height: document.documentElement.scrollHeight,
              };
            }
            """
            measurement, measurements = await stable_measure(page, script)
            actual_name = str(measurement["actual_name"] or "").strip()
            expected_name = target.platform_display_name.replace(" ", "").casefold()
            actual_key = actual_name.replace(" ", "").casefold()
            if expected_name != actual_key:
                raise ReputationAdapterError(
                    "REPUTATION_IDENTITY_MISMATCH", "易车页面车型名称与冻结映射不一致。"
                )
            score = str(info.get("score") or measurement.get("score") or "").strip() or None
            volume = str(info.get("authorCount") or measurement.get("volume") or "").strip() or None
            review_count = str(listing.get("total") or "").strip() or None
            path = output_dir / f"{target.vehicle_id}-metric.png"
            width, height, digest = await capture_region(page, path, measurement["rect"])
            return ReputationPageResult(
                vehicle_id=target.vehicle_id,
                platform_vehicle_id=target.platform_vehicle_id,
                mapping_hash=target.mapping_hash,
                final_url=normalize_series_url(page.url, target.platform_vehicle_id),
                actual_name=actual_name,
                score_raw=score,
                rank_raw=measurement.get("rank"),
                volume_raw=volume,
                review_article_count_raw=review_count,
                review_article_count_url=list_url,
                rank_scope=str(measurement.get("rank_scope") or "同级车型指数排行"),
                measurements=[{**item, "api_review_total": review_count} for item in measurements],
                full_page_path=path,
                metric_region_path=path,
                full_page_sha256=digest,
                metric_region_sha256=digest,
                width=width,
                height=height,
                metric_rect=measurement["rect"],
                duration_ms=elapsed_ms(started),
                negative_rate_raw=None,
                reputation_not_available=False,
            )
        finally:
            await context.close()


def final_url_slug(url: str) -> str | None:
    """从易车最终URL提取稳定车型拼音。"""

    match = SERIES_URL_RE.match(url)
    if match:
        return match.group("slug")
    parts = [item for item in urlsplit(url).path.split("/") if item]
    return parts[0] if parts else None
