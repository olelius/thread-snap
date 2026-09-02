"""汽车之家车型口碑页真实指标与区域截图适配器。"""

from __future__ import annotations

import re
from pathlib import Path
from time import monotonic
from urllib.parse import urlsplit

from .reputation_adapter import (
    ReputationAdapterError,
    ReputationMappingTarget,
    ReputationPageResult,
)
from .reputation_browser import (
    BrowserReputationAdapter,
    capture_region,
    elapsed_ms,
    stable_measure,
)

ADAPTER_VERSION = "autohome-reputation-v1"
VALIDATION_CONTRACT_VERSION = "autohome-reputation-mapping-v1"
VIEWPORT = {"width": 1440, "height": 1600}
SERIES_URL_RE = re.compile(r"^https://k\.autohome\.com\.cn/(?P<id>\d+)/?(?:\?.*)?$")


def normalize_series_url(url: str, expected_id: str | None = None) -> str:
    """规范为汽车之家车型口碑首页，并校验稳定车系 ID。"""

    value = url.strip()
    match = SERIES_URL_RE.match(value)
    if not match:
        raise ReputationAdapterError(
            "REPUTATION_URL_INVALID", "页面URL必须是汽车之家 k.autohome.com.cn 车型口碑页。"
        )
    series_id = match.group("id")
    if expected_id and series_id != expected_id.strip():
        raise ReputationAdapterError(
            "REPUTATION_ID_URL_MISMATCH", "页面URL中的车系ID与平台车型ID不一致。"
        )
    return f"https://k.autohome.com.cn/{series_id}/"


class AutohomeReputationAdapter(BrowserReputationAdapter):
    """从同一汽车之家页面上下文读取指标并冻结区域证据。"""

    code = "autohome"
    display_name = "汽车之家"
    adapter_version = ADAPTER_VERSION
    validation_contract_version = VALIDATION_CONTRACT_VERSION
    viewport = VIEWPORT

    async def _visit(self, browser, target: ReputationMappingTarget, output_dir: Path):
        started = monotonic()
        context = await browser.new_context(storage_state=self.storage_state, viewport=VIEWPORT)
        page = await context.new_page()
        page.set_default_timeout(self.timeout_seconds * 1000)
        try:
            expected_url = normalize_series_url(target.platform_url, target.platform_vehicle_id)
            response = await page.goto(expected_url, wait_until="domcontentloaded")
            if response is None or response.status >= 400:
                raise ReputationAdapterError(
                    "REPUTATION_PAGE_UNAVAILABLE", "汽车之家口碑页访问异常。", retryable=True
                )
            await page.wait_for_selector('div[class*="header_toolbar__car__name"]')
            await page.wait_for_selector('div[class*="score_left"]')
            api_url = (
                "https://koubeiipv6.app.autohome.com.cn/pc/series/list"
                f"?pm=3&seriesId={target.platform_vehicle_id}&pageIndex=1&pageSize=20"
                "&yearid=0&ge=0&seriesSummaryKey=0&order=0"
            )
            api_response = await context.request.get(api_url)
            if not api_response.ok:
                raise ReputationAdapterError(
                    "REPUTATION_METRICS_MISSING", "汽车之家口碑指标接口访问异常。", retryable=True
                )
            payload = await api_response.json()
            result = payload.get("result") if isinstance(payload, dict) else None
            if not isinstance(result, dict):
                raise ReputationAdapterError(
                    "REPUTATION_METRICS_MISSING", "汽车之家口碑指标接口缺少结果。", retryable=True
                )
            script = """
            () => {
              const name = document.querySelector('div[class*="header_toolbar__car__name"]');
              const score = document.querySelector('div[class*="score_left"]');
              const rank = document.querySelector('div[class*="score_hot_series"]');
              const count = document.querySelector('div[class*="list_kb_nums"]');
              if (!name || !score || !rank || !count) return null;
              const boxes = [name, score, rank, count].map((node) => node.getBoundingClientRect());
              const left = Math.max(0, Math.min(...boxes.map((box) => box.left)) - 20);
              const top = Math.max(0, Math.min(...boxes.map((box) => box.top + scrollY)) - 4);
              const right = Math.max(...boxes.map((box) => box.right)) + 20;
              const bottom = Math.max(...boxes.map((box) => box.bottom + scrollY)) + 36;
              return {
                actual_name: name.textContent.trim().split('-').pop().trim(),
                score: (score.textContent.match(/口碑评分\s*([0-9.]+)/) || [])[1] || null,
                rank: rank.textContent.trim(),
                volume: null,
                rect: {x: left, y: top, width: right-left, height: bottom-top},
                document_width: document.documentElement.scrollWidth,
                document_height: document.documentElement.scrollHeight,
              };
            }
            """
            measurement, measurements = await stable_measure(page, script)
            actual_name = str(result.get("seriesname") or measurement["actual_name"]).strip()
            if (
                target.platform_display_name.replace(" ", "").casefold()
                != actual_name.replace(" ", "").casefold()
            ):
                raise ReputationAdapterError(
                    "REPUTATION_IDENTITY_MISMATCH", "汽车之家页面车型身份与冻结映射不一致。"
                )
            rank = str(result.get("levelrank") or "").strip() or None
            score = str(result.get("average") or "").strip() or measurement.get("score")
            volume = str(result.get("averagenum") or "").strip() or None
            review_count = str(result.get("rowcount") or "").strip() or None
            if not all((score, rank, volume, review_count)):
                raise ReputationAdapterError(
                    "REPUTATION_METRICS_MISSING",
                    "汽车之家页面未完整取得口碑分、排名、口碑量或评价篇数。",
                    retryable=True,
                )
            path = output_dir / f"{target.vehicle_id}-metric.png"
            width, height, digest = await capture_region(page, path, measurement["rect"])
            final_url = normalize_series_url(page.url, target.platform_vehicle_id)
            return ReputationPageResult(
                vehicle_id=target.vehicle_id,
                platform_vehicle_id=target.platform_vehicle_id,
                mapping_hash=target.mapping_hash,
                final_url=final_url,
                actual_name=actual_name,
                score_raw=score,
                rank_raw=rank,
                volume_raw=volume,
                review_article_count_raw=review_count,
                review_article_count_url=api_url,
                rank_scope=f"{str(result.get('levelname') or '同级车型')}口碑评分排行",
                measurements=[
                    {
                        **item,
                        "api_levelrank": rank,
                        "api_levelseriescount": result.get("levelseriescount"),
                        "api_averagenum": volume,
                        "api_rowcount": review_count,
                    }
                    for item in measurements
                ],
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


def final_url_series_id(url: str) -> str | None:
    """从汽车之家最终URL提取稳定车系ID。"""

    match = SERIES_URL_RE.match(url)
    if match:
        return match.group("id")
    fallback = re.search(r"/(\d+)", urlsplit(url).path)
    return fallback.group(1) if fallback else None
