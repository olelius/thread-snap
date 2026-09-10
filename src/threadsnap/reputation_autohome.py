"""汽车之家车型口碑页真实指标与区域截图适配器。"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from time import monotonic
from urllib.parse import urlsplit

from lxml import etree, html

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

ADAPTER_VERSION = "autohome-reputation-v3-comparison-rank"
VALIDATION_CONTRACT_VERSION = "autohome-reputation-mapping-v2"
VIEWPORT = {"width": 1440, "height": 1600}


def comparison_rank(result: dict, series_id: str) -> tuple[str | None, str]:
    """按页面评分榜原始顺序匹配车系，不使用接口级别排名。"""
    title = str(result.get("cmpSeriesTitle") or "").strip()
    scope = f"autohome:comparison-score:{series_id}:{title}"
    try:
        if result.get("average") is not None and Decimal(str(result["average"])) <= 0:
            return None, scope
    except InvalidOperation:
        return None, scope
    rows = result.get("cmpSeriesScore")
    if title not in {"热门对比车系评分排行", "同级别车系评分排行"} or not isinstance(rows, list):
        return None, scope
    matches = [
        str(index + 1)
        for index, row in enumerate(rows)
        if isinstance(row, dict) and str(row.get("seriesId")) == str(series_id)
    ]
    return (matches[0] if len(matches) == 1 else None), scope
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

    def __init__(self, *args, include_circle_content_count: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        self.include_circle_content_count = include_circle_content_count

    @staticmethod
    def parse_forum_count(content: bytes, final_url: str, target: ReputationMappingTarget):
        """读取论坛顶部“帖子”总数，排除列表total、车友数与认证车主数。"""
        url = urlsplit(final_url)
        expected_path = f"/bbs/forum-c-{target.platform_vehicle_id}-1.html"
        if url.scheme != "https" or url.netloc != "club.autohome.com.cn" or url.path != expected_path:
            raise ReputationAdapterError("REPUTATION_FORUM_IDENTITY_MISMATCH", "汽车之家论坛落地URL与车型映射不一致。")
        try:
            doc = html.fromstring(content.decode("utf-8"))
            if "用户访问安全认证" in "".join(doc.xpath("//title/text()")):
                raise ReputationAdapterError("AUTH_REQUIRED", "汽车之家论坛要求完成访问验证。")
            headers = doc.xpath('//*[@id="js-bbs-info"]')
            if len(headers) != 1:
                raise ValueError("缺少唯一论坛统计区")
            header = headers[0]
            if header.get("data-bbsid") != target.platform_vehicle_id or header.get("data-bbs") != "c":
                raise ReputationAdapterError("REPUTATION_FORUM_IDENTITY_MISMATCH", "汽车之家论坛身份与车型映射不一致。")
            related = header.xpath('.//a/@href')
            expected_series = f"/{target.platform_vehicle_id}/"
            if not any(
                urlsplit("https:" + href if href.startswith("//") else href).netloc == "www.autohome.com.cn"
                and urlsplit(href).path == expected_series for href in related
            ):
                raise ReputationAdapterError("REPUTATION_FORUM_IDENTITY_MISMATCH", "论坛相关车系未对应当前车型ID。")
            items = header.xpath('.//*[contains(concat(" ",normalize-space(@class)," ")," count-item ")]')
            posts = [node for node in items if "".join(node.xpath('./text()')).strip() == "帖子"]
            if len(posts) != 1:
                raise ValueError("缺少唯一帖子计数")
            raw = "".join(posts[0].xpath('./strong/text()')).strip()
            quantity_kind = "exact"
            if re.fullmatch(r"[0-9]+", raw):
                count = int(raw)
            elif re.fullmatch(r"[0-9]+(?:\.[0-9]+)?万", raw):
                normalized = Decimal(raw[:-1]) * 10000
                if normalized != normalized.to_integral_value():
                    raise ValueError("帖子显示值的单位精度异常")
                count, quantity_kind = int(normalized), "rounded"
            else:
                raise ValueError("帖子计数不是可识别的非负数量")
        except ReputationAdapterError:
            raise
        except (ValueError, TypeError, etree.ParserError) as error:
            raise ReputationAdapterError("REPUTATION_FORUM_COUNT_INVALID", "汽车之家论坛顶部帖子总数结构异常。") from error
        return raw, {
            "collection_method": "forum_http_html", "count_source": "visible",
            "source_url": final_url, "platform_vehicle_id": target.platform_vehicle_id,
            "actual_name": header.get("data-bbsname"), "json_count": None,
            "visible_count": count, "visible_raw": f"{raw} 帖子",
            "display_count_raw": raw, "quantity_kind": quantity_kind,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "response_sha256": hashlib.sha256(content).hexdigest(),
        }

    async def _forum_count(self, context, target, started):
        """复用当前会话追加一次论坛HTML请求，使用执行项剩余时限。"""
        remaining = self.timeout_seconds - (monotonic() - started)
        if remaining <= 0:
            raise ReputationAdapterError("REPUTATION_ITEM_TIMEOUT", "口碑执行项已达到采集时限。")
        url = f"https://club.autohome.com.cn/bbs/forum-c-{target.platform_vehicle_id}-1.html?sort=topic"
        response = await context.request.get(url, timeout=remaining * 1000)
        if not response.ok:
            raise ReputationAdapterError("REPUTATION_FORUM_HTTP_ERROR", f"汽车之家论坛返回HTTP {response.status}。", retryable=response.status >= 500 or response.status == 429)
        raw, proof = self.parse_forum_count(await response.body(), response.url, target)
        return raw, response.url, proof

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
              if (!name) return null;
              const boxes = [name, score, rank, count].filter(Boolean).map((node) => node.getBoundingClientRect());
              const left = Math.max(0, Math.min(...boxes.map((box) => box.left)) - 20);
              const top = Math.max(0, Math.min(...boxes.map((box) => box.top + scrollY)) - 4);
              const right = Math.max(...boxes.map((box) => box.right)) + 20;
              const bottom = Math.max(...boxes.map((box) => box.bottom + scrollY)) + 36;
              return {
                actual_name: name.textContent.trim().split('-').pop().trim(),
                score: score ? (score.textContent.match(/口碑评分\s*([0-9.]+)/) || [])[1] || null : null,
                rank: rank ? rank.textContent.trim() || null : null,
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
            rank, rank_scope = comparison_rank(result, target.platform_vehicle_id)
            score = str(result.get("average") or "").strip() or measurement.get("score")
            volume = str(result.get("averagenum") or "").strip() or None
            review_count = str(result.get("rowcount") or "").strip() or None
            forum_raw, forum_url, forum_proof = None, None, None
            if self.include_circle_content_count:
                forum_raw, forum_url, forum_proof = await self._forum_count(context, target, started)
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
                rank_scope=rank_scope,
                measurements=[
                    {
                        **item,
                        "api_levelrank": result.get("levelrank"),
                        "api_comparison_rank": rank,
                        "api_comparison_title": result.get("cmpSeriesTitle"),
                        "api_comparison_rows": result.get("cmpSeriesScore"),
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
                circle_content_count_raw=forum_raw,
                circle_content_count_url=forum_url,
                circle_content_count_measurement=forum_proof,
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
