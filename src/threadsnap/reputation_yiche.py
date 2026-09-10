"""易车临时 URL 模式：读取已验证点评 URL，不调用 Android 或生成截图。"""

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
from .reputation_browser import BrowserReputationAdapter, elapsed_ms, stable_measure

ADAPTER_VERSION = "yiche-reputation-url-v3-mobile-metrics"
VALIDATION_CONTRACT_VERSION = "yiche-reputation-mapping-v2"
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


def _mobile_api_url(path: str, params: dict[str, object]) -> str:
    """构造APK移动接口的最小URL；该接口不使用PC cid与签名。"""
    return f"https://mapi.yiche.com/{path}?param={quote(json.dumps(params, separators=(',', ':')))}"


def parse_mobile_rank(payload: object, series_id: str) -> tuple[str | None, str, list[dict]]:
    """按移动端热门对比评分榜原始顺序与稳定车系ID读取排名。"""
    scope = f"yiche:comparison-score:{series_id}:热门对比车系评分"
    data = payload.get("data") if isinstance(payload, dict) and str(payload.get("status")) == "1" else None
    rows = data.get("serialList") if isinstance(data, dict) else None
    rows = [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
    matches: list[str] = []
    for index, row in enumerate(rows):
        if str(row.get("serialId")) != str(series_id):
            continue
        try:
            scored = float(str(row.get("rating"))) > 0
        except (TypeError, ValueError):
            scored = False
        if scored:
            matches.append(str(index + 1))
    return (matches[0] if len(matches) == 1 else None), scope, rows


def parse_owner_review_count(payload: object, series_id: str) -> tuple[str | None, str | None]:
    """从车型页合并使用的移动点评摘要读取车主点评数与参与人数。"""
    data = payload.get("data") if isinstance(payload, dict) and str(payload.get("status")) == "1" else None
    card = data.get("ratingCard") if isinstance(data, dict) else None
    if not isinstance(card, dict) or str(card.get("serialId")) != str(series_id):
        return None, None

    def count(name: str) -> str | None:
        value = card.get(name)
        return str(value) if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None

    return count("topicCount"), count("authorCount")


class YicheReputationAdapter(BrowserReputationAdapter):
    """从点评URL的真实页面/响应读取指标；页面未提供的数据保持空值。"""

    code = "yiche"
    display_name = "易车"
    adapter_version = ADAPTER_VERSION
    validation_contract_version = VALIDATION_CONTRACT_VERSION
    viewport = VIEWPORT

    def __init__(self, storage_state=None, **kwargs):
        # URL模式始终在后台浏览器运行；原生Runtime参数即使由旧调用方传入也不使用。
        kwargs["headless"] = True
        super().__init__(storage_state, **kwargs)

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

            page.on(
                "response",
                lambda response: response_tasks.append(asyncio.create_task(capture(response))),
            )
            expected_url = normalize_series_url(target.platform_url, target.platform_vehicle_id)
            response = await page.goto(expected_url, wait_until="domcontentloaded")
            if response is None or response.status >= 400:
                raise ReputationAdapterError(
                    "REPUTATION_PAGE_UNAVAILABLE", "易车点评页访问异常。", retryable=True
                )
            await page.wait_for_selector(".middle-nav-box .container")
            for _ in range(40):
                if "tags" in captured:
                    break
                await page.wait_for_timeout(250)
            if response_tasks:
                await asyncio.gather(*response_tasks, return_exceptions=True)
            if "tags" not in captured:
                raise ReputationAdapterError(
                    "REPUTATION_METRICS_MISSING", "易车点评指标接口访问异常。", retryable=True
                )
            tags_payload = captured["tags"]
            info = ((tags_payload or {}).get("data") or {}).get("pointCommontInfo") or {}
            if str(info.get("serialId") or "") != target.platform_vehicle_id:
                raise ReputationAdapterError(
                    "REPUTATION_IDENTITY_MISMATCH", "易车页面车系ID与冻结映射不一致。"
                )
            rank_url = _mobile_api_url(
                "app_review/api/v1/review/serial_rating_sort",
                {"serialId": target.platform_vehicle_id},
            )
            owner_review_url = _mobile_api_url(
                "app_review/api/v1/review/overview_review_list",
                {"serialId": target.platform_vehicle_id},
            )
            mobile_payloads: dict[str, object] = {}
            mobile_errors: dict[str, str] = {}
            for name, url in (("rank", rank_url), ("owner_review", owner_review_url)):
                try:
                    api_response = await context.request.get(url)
                    if api_response.status == 200:
                        mobile_payloads[name] = await api_response.json()
                    else:
                        mobile_errors[name] = f"HTTP {api_response.status}"
                except Exception as error:
                    mobile_errors[name] = f"{type(error).__name__}: {error}"
            script = """
            () => {
              const identity = document.querySelector('.middle-nav-box .container');
              const metrics = document.querySelector('.cm-taglist-box');
              const title = document.querySelector('#commentBrand');
              const serialTitle = title ? Array.from(title.querySelectorAll('a')).find(
                node => !node.querySelector('img') && node.textContent.trim()
              ) : null;
              const score = document.querySelector('.cm-list-score-val');
              const volume = document.querySelector('.cm-list-count');
              const legacyRank = document.querySelector('.brand-rank');
              if (!identity || !title) return null;
              const boxes = [identity, metrics].filter(Boolean).map((node) => node.getBoundingClientRect());
              const left = Math.max(0, Math.min(...boxes.map((box) => box.left)) - 20);
              const top = Math.max(0, Math.min(...boxes.map((box) => box.top + scrollY)) - 4);
              const right = Math.max(...boxes.map((box) => box.right)) + 20;
              const bottom = Math.max(...boxes.map((box) => box.bottom + scrollY)) + 36;
              return {
                actual_name: (serialTitle || title).textContent.replace(/点评/g, '').trim(),
                score: score ? (score.textContent.match(/[0-9.]+/) || [])[0] || null : null,
                legacy_rank: legacyRank ? (legacyRank.textContent.match(/第\s*(\d+)\s*名/) || [])[1] || null : null,
                rank: null,
                rank_scope: null,
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
            rank, rank_scope, rank_rows = parse_mobile_rank(
                mobile_payloads.get("rank"), target.platform_vehicle_id
            )
            owner_review_count, mobile_author_count = parse_owner_review_count(
                mobile_payloads.get("owner_review"), target.platform_vehicle_id
            )
            # 暂无评分时的0.00是页面占位，不作为真实口碑分；点评总数0则是合法数量。
            if not info.get("authorCount") and measurement.get("volume") in (None, "", "0"):
                volume = None
                if score in (None, "0", "0.0", "0.00"):
                    score = None
            # 该阶段只读取URL，截图门禁与文件写入都停用，不能用空白PNG占位。
            return ReputationPageResult(
                vehicle_id=target.vehicle_id,
                platform_vehicle_id=target.platform_vehicle_id,
                mapping_hash=target.mapping_hash,
                final_url=normalize_series_url(page.url, target.platform_vehicle_id),
                actual_name=actual_name,
                score_raw=score,
                rank_raw=rank,
                volume_raw=volume,
                review_article_count_raw=None,
                review_article_count_url=None,
                rank_scope=rank_scope,
                measurements=[
                    {
                        **item,
                        "legacy_index_rank": item.get("legacy_rank"),
                        "mobile_rank_url": rank_url,
                        "mobile_rank_rows": rank_rows,
                        "mobile_owner_review_url": owner_review_url,
                        "mobile_owner_review_count": owner_review_count,
                        "mobile_author_count": mobile_author_count,
                        "mobile_errors": mobile_errors,
                    }
                    for item in measurements
                ],
                full_page_path=None,
                metric_region_path=None,
                full_page_sha256=None,
                metric_region_sha256=None,
                width=0,
                height=0,
                metric_rect=measurement["rect"],
                duration_ms=elapsed_ms(started),
                negative_rate_raw=None,
                reputation_not_available=score is None and volume is None,
                owner_review_count_raw=owner_review_count,
                owner_review_count_url=owner_review_url,
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
