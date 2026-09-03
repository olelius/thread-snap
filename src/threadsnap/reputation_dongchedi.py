"""懂车帝口碑页面的轻量取数与按需浏览器证据适配器。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import threading
import time
from dataclasses import replace
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

from lxml import html
from patchright.async_api import Browser, BrowserContext, Page, async_playwright
from patchright.async_api import Error as PlaywrightError
from PIL import Image

from .browser_runtime import browser_launch_args
from .reputation_adapter import (
    ReputationAdapterError,
    ReputationMappingTarget,
    ReputationPageResult,
)
from .scrapling_transport import ExecutionScopeKey, ScraplingHttpPool

logger = logging.getLogger(__name__)

ADAPTER_VERSION = "dongchedi-reputation-v9-scrapling"
VALIDATION_CONTRACT_VERSION = "dongchedi-reputation-mapping-v1"
VIEWPORT = {"width": 1440, "height": 1000}
NEGATIVE_RATE_API_URL = (
    "https://api.dcarapi.com/motor/car_score/api/v1/landing_page/get_detail/"
)
NEGATIVE_RATE_APP_PARAMS = {
    "aid": "36",
    "app_name": "automobile",
    "version_code": "921",
    "version_name": "9.2.1",
    "manifest_version_code": "921",
    "device_platform": "android",
    "os": "android",
}
NEGATIVE_RATE_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "com.ss.android.auto/921 (Linux; Android 13)",
    "x-tt-appid": "36",
    "x-ss-dp": "36",
}
SERIES_URL_RE = re.compile(
    r"^https://www\.dongchedi\.com/auto/series/(?:score/)?(?P<id>\d+)(?:-x-x-x-x-x)?/?(?:\?.*)?$"
)
VOLUME_RE = re.compile(r"共\s*([0-9,]+)\s*人评价")


def normalize_series_url(url: str, expected_id: str | None = None) -> str:
    """只接受懂车帝车型或口碑页，并核对URL中的稳定车型ID。"""

    value = url.strip()
    match = SERIES_URL_RE.match(value)
    if not match:
        raise ReputationAdapterError(
            "REPUTATION_URL_INVALID",
            "页面URL必须是懂车帝 auto/series 车型页或 score 口碑页。",
        )
    if expected_id and match.group("id") != expected_id.strip():
        raise ReputationAdapterError(
            "REPUTATION_ID_URL_MISMATCH",
            "页面URL中的车型ID与平台车型ID不一致。",
        )
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _name_key(value: str) -> str:
    return re.sub(r"[\s·._-]+", "", value).casefold()


def _metric_rect(measurement: dict[str, Any]) -> dict[str, float]:
    boxes = [
        value
        for key in (
            "heading_box",
            "score_box",
            "volume_box",
            "rank_box",
            "availability_box",
        )
        if isinstance((value := measurement.get(key)), dict)
    ]
    if not boxes:
        raise ReputationAdapterError(
            "REPUTATION_EVIDENCE_REGION_MISSING",
            "页面身份与指标区域没有形成可截图的稳定边界。",
        )
    left = max(0.0, min(float(item["x"]) for item in boxes) - 20)
    # 页面标题上方紧邻一条不属于指标卡的装饰横条；截图窗口整体下移16px：
    # 顶部由20px收紧为4px，底部由20px扩展为36px，保持原截图高度。
    top = max(0.0, min(float(item["y"]) for item in boxes) - 4)
    right = max(float(item["x"]) + float(item["width"]) for item in boxes) + 20
    bottom = max(float(item["y"]) + float(item["height"]) for item in boxes) + 36
    return {"x": left, "y": top, "width": right - left, "height": bottom - top}


class DongchediReputationAdapter:
    """日常巡检轻量取数，只有必要证据项才进入有界浏览器页面池。"""

    code = "dongchedi"
    display_name = "懂车帝"
    adapter_version = ADAPTER_VERSION
    validation_contract_version = VALIDATION_CONTRACT_VERSION

    def __init__(
        self,
        storage_state: dict[str, Any] | None,
        *,
        concurrency: int = 2,
        headless: bool = False,
        timeout_seconds: int = 90,
        batch_timeout_seconds: int = 45 * 60,
        evidence_policy: Callable[[ReputationMappingTarget, dict[str, Any]], bool] | None = None,
        prefer_http_first: bool = False,
        include_review_article_count: bool = False,
        include_negative_rate: bool = False,
        execution_scope: ExecutionScopeKey | None = None,
        global_limiter: threading.Semaphore | None = None,
    ) -> None:
        self.storage_state = storage_state
        self.concurrency = max(1, min(int(concurrency), 8))
        self.headless = headless
        self.timeout_seconds = timeout_seconds
        self.batch_timeout_seconds = max(1, int(batch_timeout_seconds))
        self.evidence_policy = evidence_policy
        self.prefer_http_first = prefer_http_first
        self.include_review_article_count = include_review_article_count
        self.include_negative_rate = include_negative_rate
        self.global_limiter = global_limiter
        self.http = ScraplingHttpPool(
            storage_state,
            timeout_seconds=timeout_seconds,
            scope=(execution_scope or ExecutionScopeKey()).bind_platform(
                "dongchedi-reputation"
            ),
        )

    def _http_session(self) -> Any:
        """返回当前线程独享的 Scrapling FetcherSession 适配器。"""

        return self.http.session()

    def close(self) -> None:
        """关闭巡检线程创建的全部 Scrapling Session。"""

        self.http.close()

    async def _acquire_global_slot(self) -> None:
        if self.global_limiter is not None:
            await asyncio.to_thread(self.global_limiter.acquire)

    def _release_global_slot(self) -> None:
        if self.global_limiter is not None:
            self.global_limiter.release()

    @staticmethod
    def _attitude_count(
        items: list[Any], *, part_id: str, names: set[str]
    ) -> int | None:
        """按稳定标签ID读取优缺点数量，名称仅作为接口兼容兜底。"""

        candidate = next(
            (
                item
                for item in items
                if isinstance(item, dict) and str(item.get("part_id")) == part_id
            ),
            None,
        )
        if candidate is None:
            candidate = next(
                (
                    item
                    for item in items
                    if isinstance(item, dict)
                    and str(item.get("tag_name") or "").split("(", 1)[0] in names
                ),
                None,
            )
        if candidate is None:
            return None
        count = candidate.get("count")
        if isinstance(count, bool):
            return None
        try:
            value = int(count)
        except (TypeError, ValueError):
            return None
        return value if value >= 0 else None

    def _visit_negative_rate(
        self, target: ReputationMappingTarget
    ) -> tuple[str | None, str, int, int]:
        """使用现有平台车型ID读取APP优缺点数量并计算整数差评率。"""

        params = {
            "series_id": target.platform_vehicle_id,
            "car_id": "",
            "only_owner": "0",
            "year_id": "",
            **NEGATIVE_RATE_APP_PARAMS,
        }
        try:
            response = self._http_session().get(
                NEGATIVE_RATE_API_URL,
                params=params,
                headers=NEGATIVE_RATE_HEADERS,
                timeout=self.timeout_seconds,
            )
        except Exception as error:
            raise ReputationAdapterError(
                "REPUTATION_NEGATIVE_RATE_NETWORK_ERROR",
                f"直接访问车型差评率接口失败：{error}",
                retryable=True,
            ) from error
        source_url = str(response.url)
        if response.status_code >= 500 or response.status_code == 429:
            raise ReputationAdapterError(
                "REPUTATION_NEGATIVE_RATE_SERVER_ERROR",
                f"车型差评率接口返回HTTP {response.status_code}。",
                retryable=True,
            )
        if response.status_code >= 400:
            raise ReputationAdapterError(
                "REPUTATION_NEGATIVE_RATE_STATUS_ERROR",
                f"车型差评率接口返回HTTP {response.status_code}。",
            )
        try:
            payload = response.json()
        except (TypeError, ValueError) as error:
            raise ReputationAdapterError(
                "REPUTATION_NEGATIVE_RATE_RESPONSE_INVALID",
                "车型差评率接口没有返回可解析的JSON。",
                retryable=True,
            ) from error
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            raise ReputationAdapterError(
                "REPUTATION_NEGATIVE_RATE_DATA_MISSING",
                "车型差评率接口缺少数据对象。",
                retryable=True,
            )
        series = data.get("series_info")
        actual_name = str(series.get("series_name") or "") if isinstance(series, dict) else ""
        if not actual_name or _name_key(actual_name) != _name_key(target.platform_display_name):
            raise ReputationAdapterError(
                "REPUTATION_NEGATIVE_RATE_IDENTITY_MISMATCH",
                "车型差评率接口返回的车型身份与当前映射不一致。",
            )
        tag_info_v2 = data.get("tag_info_v2")
        items = (
            tag_info_v2.get("hierarchical_tag_list")
            if isinstance(tag_info_v2, dict)
            else None
        )
        if not isinstance(items, list):
            tag_info = data.get("tag_info")
            items = tag_info.get("special_tag_list") if isinstance(tag_info, dict) else None
        if not isinstance(items, list) or not items:
            review_count_info = data.get("review_count_info")
            total_review = (
                review_count_info.get("total")
                if isinstance(review_count_info, dict)
                else None
            )
            if total_review == 0:
                return None, source_url, 0, 0
            # 部分车型（尤其未上市或暂无评价车型）接口会返回车型身份但不带标签。
            # 这只表示差评率暂无可展示值，不应阻断其他指标和页面证据。
            return None, source_url, None, None
        positive_count = self._attitude_count(items, part_id="3", names={"优点", "好评"})
        negative_count = self._attitude_count(items, part_id="4", names={"缺点", "差评"})
        if positive_count is None or negative_count is None:
            raise ReputationAdapterError(
                "REPUTATION_NEGATIVE_RATE_COUNTS_INVALID",
                "车型差评率接口的优缺点数量不可解析。",
                retryable=True,
            )
        total = positive_count + negative_count
        if total == 0:
            return None, source_url, positive_count, negative_count
        rate = (
            Decimal(negative_count) / Decimal(total) * Decimal(100)
        ).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        return f"{rate}%", source_url, positive_count, negative_count

    @staticmethod
    def _validate_identity(
        target: ReputationMappingTarget,
        final_url: str,
        actual_name: str,
    ) -> None:
        if final_url_series_id(final_url) != target.platform_vehicle_id:
            raise ReputationAdapterError(
                "REPUTATION_IDENTITY_REDIRECT",
                "页面跳转后的稳定车型ID与配置不一致。",
            )
        if _name_key(actual_name) != _name_key(target.platform_display_name):
            raise ReputationAdapterError(
                "REPUTATION_IDENTITY_NAME_MISMATCH",
                f"页面车型名“{actual_name}”与配置展示名“{target.platform_display_name}”不一致。",
            )

    @staticmethod
    def _confirmed_no_reputation_data(
        *,
        score_raw: str | None,
        rank_raw: str | None,
        volume_raw: str | None,
        review_article_count_raw: str | None,
        page_not_available: bool,
        negative_rate_positive_count: int | None,
        negative_rate_negative_count: int | None,
        require_negative_rate_confirmation: bool,
    ) -> bool:
        """只在页面零评价状态与现有指标空值一致时确认平台暂无。"""

        if not page_not_available or any(
            value is not None
            for value in (
                score_raw,
                rank_raw,
                volume_raw,
                review_article_count_raw,
            )
        ):
            return False
        if not require_negative_rate_confirmation:
            return True
        return (negative_rate_positive_count, negative_rate_negative_count) in {
            (0, 0),
            (None, None),
        }

    @staticmethod
    async def _measure(page: Page) -> dict[str, Any]:
        return await page.evaluate(
            """() => {
              const visible = (e) => {
                if (!e) return false;
                const r = e.getBoundingClientRect();
                const s = getComputedStyle(e);
                return r.width > 0 && r.height > 0 && s.display !== 'none' &&
                  s.visibility !== 'hidden';
              };
              const box = (e) => {
                if (!visible(e)) return null;
                const r = e.getBoundingClientRect();
                return {x:r.x + scrollX,y:r.y + scrollY,width:r.width,height:r.height};
              };
              const text = (e) => (e?.innerText || e?.textContent || '').trim();
              const heading = [...document.querySelectorAll('h1')].find(visible);
              let actualName = text(heading).replace(/^懂/, '').trim();
              const rankRoot = [...document.querySelectorAll('.rank-wrapper')].find(visible);
              const rows = rankRoot ? [...rankRoot.querySelectorAll('li')].filter((e) =>
                visible(e) && e.querySelector('.car-name')) : [];
              const current = rows.find((e) => e.className.includes('tw-text-common-yellow'));
              if (current?.querySelector('.car-name')) {
                actualName = text(current.querySelector('.car-name'));
              }
              const scoreNode = current?.querySelector('.score-wrapper');
              const scoreText = text(scoreNode);
              const volumeNode = [...document.querySelectorAll('span,div')].find((e) =>
                visible(e) && /^共\\s*[0-9,]+\\s*人评价$/.test(text(e)));
              const volumeText = text(volumeNode);
              let reviewArticleCount = null;
              let reputationNotAvailable = false;
              let hasOfficialPrice = null;
              try {
                const nextData = JSON.parse(document.querySelector('#__NEXT_DATA__')?.textContent || '{}');
                const pageProps = nextData?.props?.pageProps || {};
                const count = pageProps?.reviewListData?.total_count;
                if (Number.isInteger(count) && count >= 0) reviewArticleCount = String(count);
                const head = pageProps?.seriesHomeHead;
                const totalScore = head?.total_score;
                const totalReviewCount = head?.total_review_count;
                hasOfficialPrice = head?.has_official_price;
                reputationNotAvailable = typeof totalScore === 'number' && totalScore === 0 &&
                  typeof totalReviewCount === 'number' && totalReviewCount === 0;
              } catch (_) {}
              const ratingPlaceholderNode = reputationNotAvailable
                ? [...document.querySelectorAll('span,div')]
                    .filter((e) => visible(e) && text(e).includes('懂车分') && text(e).length <= 20)
                    .sort((a, b) => {
                      const ar = a.getBoundingClientRect();
                      const br = b.getBoundingClientRect();
                      return ar.width * ar.height - br.width * br.height;
                    })[0] || null
                : null;
              const pricePlaceholderNode = reputationNotAvailable && hasOfficialPrice === false
                ? [...document.querySelectorAll('span,div')].find((e) =>
                    visible(e) && text(e) === '暂无报价')
                : null;
              const availabilityNode = ratingPlaceholderNode || pricePlaceholderNode;
              const rankScope = rankRoot ? '同级车评分' : '同级车评分';
              const scoreHero = [...document.querySelectorAll('.tw-text-common-yellow')]
                .find((e) => visible(e) && /^\\d+(?:\\.\\d+)?$/.test(text(e)));
              return {
                actual_name: actualName,
                score_raw: scoreText && scoreText !== '-' ? scoreText : null,
                rank_raw: scoreText && scoreText !== '-' && current
                  ? String(rows.indexOf(current) + 1) : null,
                volume_raw: volumeText || null,
                review_article_count_raw: reviewArticleCount,
                reputation_not_available: reputationNotAvailable,
                rank_scope: rankScope,
                heading_box: box(heading),
                score_box: box(scoreHero),
                volume_box: box(volumeNode),
                rank_box: box(rankRoot),
                availability_box: box(availabilityNode),
                document_width: Math.max(document.documentElement.scrollWidth, document.body?.scrollWidth || 0),
                document_height: Math.max(document.documentElement.scrollHeight, document.body?.scrollHeight || 0),
              };
            }"""
        )

    @staticmethod
    def _stable_key(value: dict[str, Any]) -> tuple[Any, ...]:
        def rounded_box(name: str) -> tuple[float, ...] | None:
            box = value.get(name)
            if not isinstance(box, dict):
                return None
            return tuple(round(float(box[key]), 1) for key in ("x", "y", "width", "height"))

        return (
            value.get("actual_name"),
            value.get("score_raw"),
            value.get("rank_raw"),
            value.get("volume_raw"),
            value.get("review_article_count_raw"),
            value.get("reputation_not_available"),
            value.get("rank_scope"),
            rounded_box("heading_box"),
            rounded_box("score_box"),
            rounded_box("volume_box"),
            rounded_box("rank_box"),
            rounded_box("availability_box"),
        )

    @staticmethod
    async def _freeze_layout(page: Page) -> None:
        await page.add_style_tag(
            content=(
                "html{scroll-behavior:auto!important;scrollbar-width:none!important}"
                "html::-webkit-scrollbar,body::-webkit-scrollbar{display:none!important}"
                "*,*::before,*::after{animation:none!important;transition:none!important}"
            )
        )
        await page.evaluate("() => window.scrollTo({top:0,left:0,behavior:'instant'})")

    @staticmethod
    def _browser_runtime_error(
        target: ReputationMappingTarget,
        stage: str,
        error: PlaywrightError,
    ) -> ReputationAdapterError:
        """记录浏览器底层诊断，并转换为可执行一次有界重试的稳定业务错误。"""

        logger.warning(
            "口碑真实页面浏览器错误：vehicle_id=%s platform_vehicle_id=%s stage=%s "
            "type=%s detail=%s",
            target.vehicle_id,
            target.platform_vehicle_id,
            stage,
            type(error).__name__,
            str(error),
            exc_info=(type(error), error, error.__traceback__),
        )
        return ReputationAdapterError(
            "REPUTATION_BROWSER_RUNTIME_ERROR",
            f"浏览器页面在{stage}阶段暂时失败。",
            retryable=True,
        )

    async def _visit(
        self,
        browser: Browser,
        target: ReputationMappingTarget,
        output_dir: Path,
        *,
        force_capture: bool = False,
    ) -> ReputationPageResult:
        started = time.monotonic()
        context: BrowserContext | None = None
        stage = "创建页面上下文"
        try:
            context = await browser.new_context(
                storage_state=self.storage_state,
                viewport=VIEWPORT,
                device_scale_factor=1,
                locale="zh-CN",
            )
            stage = "创建页面"
            page = await context.new_page()
            page.set_default_timeout(self.timeout_seconds * 1000)
            stage = "页面导航"
            response = await page.goto(
                target.platform_url,
                wait_until="domcontentloaded",
                timeout=self.timeout_seconds * 1000,
            )
            if "/login-required" in page.url:
                raise ReputationAdapterError("AUTH_REQUIRED", "懂车帝共享Session需要更新。")
            if response and response.status >= 500:
                raise ReputationAdapterError(
                    "REPUTATION_PAGE_SERVER_ERROR",
                    f"平台页面返回HTTP {response.status}。",
                    retryable=True,
                )
            stage = "等待车型标题"
            await page.locator("h1:visible").first.wait_for(state="visible", timeout=15_000)
            if "/login-required" in page.url:
                raise ReputationAdapterError("AUTH_REQUIRED", "懂车帝共享Session需要更新。")
            await page.wait_for_timeout(1800)
            stage = "冻结页面布局"
            await self._freeze_layout(page)
            measurements: list[dict[str, Any]] = []
            stage = "测量页面指标"
            for _ in range(3):
                measurements.append(await self._measure(page))
                await page.wait_for_timeout(350)
            if len({self._stable_key(item) for item in measurements}) != 1:
                raise ReputationAdapterError(
                    "REPUTATION_PAGE_UNSTABLE",
                    "车型身份、指标文字或页面边界连续三次测量不一致。",
                    retryable=True,
                )
            current = measurements[-1]
            actual_name = str(current.get("actual_name") or "").strip()
            if not actual_name:
                raise ReputationAdapterError(
                    "REPUTATION_IDENTITY_MISSING", "页面没有可验证的车型身份。"
                )
            self._validate_identity(target, page.url, actual_name)
            score_raw = current.get("score_raw")
            rank_raw = current.get("rank_raw")
            volume_text = current.get("volume_raw")
            volume_match = VOLUME_RE.fullmatch(str(volume_text)) if volume_text else None
            volume_raw = volume_match.group(1).replace(",", "") if volume_match else None
            if (score_raw is None) != (rank_raw is None):
                raise ReputationAdapterError(
                    "REPUTATION_METRIC_CONTRACT",
                    "口碑分与同级排名的可用状态不一致。",
                )
            metric_rect = _metric_rect(current)
            review_article_count_raw = current.get("review_article_count_raw")
            review_article_count_url: str | None = None
            negative_rate_raw: str | None = None
            negative_rate_url: str | None = None
            negative_rate_positive_count: int | None = None
            negative_rate_negative_count: int | None = None
            if self.include_negative_rate:
                (
                    negative_rate_raw,
                    negative_rate_url,
                    negative_rate_positive_count,
                    negative_rate_negative_count,
                ) = await asyncio.to_thread(self._visit_negative_rate, target)
            reputation_not_available = self._confirmed_no_reputation_data(
                score_raw=str(score_raw) if score_raw is not None else None,
                rank_raw=str(rank_raw) if rank_raw is not None else None,
                volume_raw=volume_raw,
                review_article_count_raw=(
                    str(review_article_count_raw)
                    if review_article_count_raw is not None
                    else None
                ),
                page_not_available=bool(current.get("reputation_not_available")),
                negative_rate_positive_count=negative_rate_positive_count,
                negative_rate_negative_count=negative_rate_negative_count,
                require_negative_rate_confirmation=self.include_negative_rate,
            )
            if self.include_review_article_count:
                if review_article_count_raw is None and not reputation_not_available:
                    raise ReputationAdapterError(
                        "REPUTATION_REVIEW_ARTICLE_COUNT_MISSING",
                        "口碑评分页未返回可识别的评价篇数。",
                        retryable=True,
                    )
                review_article_count_url = page.url
            capture = (
                force_capture
                or self.evidence_policy is None
                or self.evidence_policy(target, current)
            )
            metric_path: Path | None = None
            digest: str | None = None
            width = int(round(metric_rect["width"]))
            height = int(round(metric_rect["height"]))
            if capture:
                target_dir = output_dir / target.vehicle_id
                target_dir.mkdir(parents=True, exist_ok=False)
                document_width = float(current.get("document_width") or 0)
                document_height = float(current.get("document_height") or 0)
                if (
                    metric_rect["x"] < 0
                    or metric_rect["y"] < 0
                    or metric_rect["x"] + metric_rect["width"] > document_width
                    or metric_rect["y"] + metric_rect["height"] > document_height
                ):
                    raise ReputationAdapterError(
                        "REPUTATION_EVIDENCE_REGION_INVALID",
                        "指标区域超出页面边界。",
                    )
                metric_path = target_dir / "region.png"
                stage = "截取指标证据"
                await page.screenshot(
                    path=str(metric_path),
                    clip=metric_rect,
                    animations="disabled",
                )
                with Image.open(metric_path) as source:
                    width, height = source.size
                if not metric_path.is_file():
                    raise ReputationAdapterError(
                        "REPUTATION_EVIDENCE_WRITE_FAILED", "真实页面证据写入失败。"
                    )
                digest = _sha256(metric_path)
            return ReputationPageResult(
                vehicle_id=target.vehicle_id,
                platform_vehicle_id=target.platform_vehicle_id,
                mapping_hash=target.mapping_hash,
                final_url=page.url,
                actual_name=actual_name,
                score_raw=str(score_raw) if score_raw is not None else None,
                rank_raw=str(rank_raw) if rank_raw is not None else None,
                volume_raw=volume_raw,
                review_article_count_raw=review_article_count_raw,
                review_article_count_url=review_article_count_url,
                rank_scope=str(current.get("rank_scope") or "同级车评分"),
                measurements=measurements,
                full_page_path=metric_path,
                metric_region_path=metric_path,
                full_page_sha256=digest,
                metric_region_sha256=digest,
                width=width,
                height=height,
                metric_rect=metric_rect,
                duration_ms=round((time.monotonic() - started) * 1000),
                negative_rate_raw=negative_rate_raw,
                negative_rate_url=negative_rate_url,
                negative_rate_positive_count=negative_rate_positive_count,
                negative_rate_negative_count=negative_rate_negative_count,
                reputation_not_available=reputation_not_available,
            )
        except PlaywrightError as error:
            raise self._browser_runtime_error(target, stage, error) from error
        finally:
            if context is not None:
                try:
                    await context.close()
                except PlaywrightError as error:
                    # 结果或原始异常已经确定时，关闭上下文失败只记运维诊断，不能覆盖业务结果。
                    logger.warning(
                        "口碑页面上下文关闭失败：vehicle_id=%s platform_vehicle_id=%s "
                        "type=%s detail=%s",
                        target.vehicle_id,
                        target.platform_vehicle_id,
                        type(error).__name__,
                        str(error),
                        exc_info=(type(error), error, error.__traceback__),
                    )

    @staticmethod
    def _node_text(node: Any) -> str:
        """读取 SSR 节点的可见文本，并折叠布局空白。"""

        return " ".join(str(node.text_content()).split())

    @staticmethod
    def _review_page_state(document: Any) -> tuple[str | None, bool]:
        """读取评价篇数，并识别服务端明确给出的零评分、零评价状态。"""

        nodes = document.xpath("//script[@id='__NEXT_DATA__']/text()")
        if not nodes:
            return None, False
        try:
            payload = json.loads(str(nodes[0]))
            page_props = payload["props"]["pageProps"]
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None, False
        review_list = page_props.get("reviewListData")
        count = review_list.get("total_count") if isinstance(review_list, dict) else None
        count_raw = (
            str(count)
            if isinstance(count, int) and not isinstance(count, bool) and count >= 0
            else None
        )
        head = page_props.get("seriesHomeHead")
        total_score = head.get("total_score") if isinstance(head, dict) else None
        total_review_count = (
            head.get("total_review_count") if isinstance(head, dict) else None
        )
        no_reputation_data = (
            isinstance(total_score, (int, float))
            and not isinstance(total_score, bool)
            and total_score == 0
            and isinstance(total_review_count, int)
            and not isinstance(total_review_count, bool)
            and total_review_count == 0
        )
        return count_raw, no_reputation_data

    @classmethod
    def _parse_http_page(
        cls,
        target: ReputationMappingTarget,
        final_url: str,
        content: bytes,
        *,
        duration_ms: int,
    ) -> ReputationPageResult:
        """从服务端直出的口碑页 HTML 解析与浏览器相同的业务字段。"""

        try:
            document = html.fromstring(content.decode("utf-8"))
        except (TypeError, UnicodeDecodeError, ValueError) as error:
            raise ReputationAdapterError(
                "REPUTATION_HTTP_DOCUMENT_INVALID",
                "口碑页面没有返回可解析的HTML文档。",
                retryable=True,
            ) from error

        rank_roots = document.xpath(
            "//*[contains(concat(' ',normalize-space(@class),' '),' rank-wrapper ')]"
        )
        current_row: Any | None = None
        rows: list[Any] = []
        for root in rank_roots:
            candidate_rows = root.xpath(
                ".//li[.//*[contains(concat(' ',normalize-space(@class),' '),' car-name ')]]"
            )
            candidate_current = next(
                (
                    row
                    for row in candidate_rows
                    if "tw-text-common-yellow" in str(row.get("class") or "").split()
                ),
                None,
            )
            if candidate_current is not None:
                rows = candidate_rows
                current_row = candidate_current
                break
        heading_nodes = [
            node
            for node in document.xpath("//h1")
            if "tw-hidden" not in str(node.get("class") or "").split()
        ]
        actual_name = cls._node_text(heading_nodes[0]).removeprefix("懂").strip() if heading_nodes else ""
        score_raw: str | None = None
        rank_raw: str | None = None
        if current_row is not None:
            name_nodes = current_row.xpath(
                ".//*[contains(concat(' ',normalize-space(@class),' '),' car-name ')]"
            )
            score_nodes = current_row.xpath(
                ".//*[contains(concat(' ',normalize-space(@class),' '),' score-wrapper ')]"
            )
            if name_nodes:
                actual_name = cls._node_text(name_nodes[0])
            score_text = cls._node_text(score_nodes[0]) if score_nodes else ""
            score_raw = score_text if score_text and score_text != "-" else None
            rank_raw = str(rows.index(current_row) + 1) if score_raw is not None else None
        if not actual_name:
            raise ReputationAdapterError(
                "REPUTATION_IDENTITY_MISSING",
                "口碑页面直出内容没有可验证的车型身份。",
                retryable=True,
            )
        cls._validate_identity(target, final_url, actual_name)

        volume_raw: str | None = None
        volume_text: str | None = None
        for node in document.xpath("//span|//div"):
            text = cls._node_text(node)
            match = VOLUME_RE.fullmatch(text)
            if match:
                volume_text = text
                volume_raw = match.group(1).replace(",", "")
                break
        review_article_count_raw, reputation_not_available = cls._review_page_state(document)
        measurement = {
            "actual_name": actual_name,
            "score_raw": score_raw,
            "rank_raw": rank_raw,
            "volume_raw": volume_text,
            "review_article_count_raw": review_article_count_raw,
            "reputation_not_available": reputation_not_available,
            "rank_scope": "同级车评分",
            "collection_method": "http_ssr",
        }
        return ReputationPageResult(
            vehicle_id=target.vehicle_id,
            platform_vehicle_id=target.platform_vehicle_id,
            mapping_hash=target.mapping_hash,
            final_url=final_url,
            actual_name=actual_name,
            score_raw=score_raw,
            rank_raw=rank_raw,
            volume_raw=volume_raw,
            review_article_count_raw=review_article_count_raw,
            review_article_count_url=(final_url if review_article_count_raw is not None else None),
            rank_scope="同级车评分",
            measurements=[measurement],
            full_page_path=None,
            metric_region_path=None,
            full_page_sha256=None,
            metric_region_sha256=None,
            width=0,
            height=0,
            metric_rect={},
            duration_ms=duration_ms,
            reputation_not_available=reputation_not_available,
        )

    def _visit_http(self, target: ReputationMappingTarget) -> ReputationPageResult:
        """直接请求车型口碑 URL；该阶段不启动浏览器，也不加载图片资源。"""

        started = time.monotonic()
        try:
            response = self._http_session().get(
                target.platform_url,
                timeout=self.timeout_seconds,
                allow_redirects=True,
            )
        except Exception as error:
            raise ReputationAdapterError(
                "REPUTATION_HTTP_NETWORK_ERROR",
                f"直接访问口碑页面失败：{error}",
                retryable=True,
            ) from error
        final_url = str(response.url)
        body = bytes(response.content or b"")
        if "/login-required" in urlsplit(final_url).path or b"login-required" in body[:200_000].lower():
            raise ReputationAdapterError("AUTH_REQUIRED", "懂车帝共享Session需要更新。")
        if response.status_code >= 500 or response.status_code == 429:
            raise ReputationAdapterError(
                "REPUTATION_PAGE_SERVER_ERROR",
                f"平台页面返回HTTP {response.status_code}。",
                retryable=True,
            )
        if response.status_code >= 400:
            raise ReputationAdapterError(
                "REPUTATION_HTTP_STATUS_ERROR",
                f"直接访问口碑页面返回HTTP {response.status_code}。",
            )
        if not body:
            raise ReputationAdapterError(
                "REPUTATION_HTTP_DOCUMENT_EMPTY",
                "直接访问口碑页面返回空文档。",
                retryable=True,
            )
        result = self._parse_http_page(
            target,
            final_url,
            body,
            duration_ms=round((time.monotonic() - started) * 1000),
        )
        negative_rate_raw: str | None = None
        negative_rate_url: str | None = None
        negative_rate_positive_count: int | None = None
        negative_rate_negative_count: int | None = None
        if self.include_negative_rate:
            (
                negative_rate_raw,
                negative_rate_url,
                negative_rate_positive_count,
                negative_rate_negative_count,
            ) = self._visit_negative_rate(target)
        reputation_not_available = self._confirmed_no_reputation_data(
            score_raw=result.score_raw,
            rank_raw=result.rank_raw,
            volume_raw=result.volume_raw,
            review_article_count_raw=result.review_article_count_raw,
            page_not_available=result.reputation_not_available,
            negative_rate_positive_count=negative_rate_positive_count,
            negative_rate_negative_count=negative_rate_negative_count,
            require_negative_rate_confirmation=self.include_negative_rate,
        )
        if self.include_review_article_count:
            if result.review_article_count_raw is None and not reputation_not_available:
                raise ReputationAdapterError(
                    "REPUTATION_REVIEW_ARTICLE_COUNT_MISSING",
                    "口碑评分页未返回可识别的评价篇数。",
                    retryable=True,
                )
        return replace(
            result,
            duration_ms=round((time.monotonic() - started) * 1000),
            review_article_count_url=(
                result.final_url
                if result.review_article_count_raw is not None
                or reputation_not_available
                else None
            ),
            negative_rate_raw=negative_rate_raw,
            negative_rate_url=negative_rate_url,
            negative_rate_positive_count=negative_rate_positive_count,
            negative_rate_negative_count=negative_rate_negative_count,
            reputation_not_available=reputation_not_available,
        )

    async def _validate_browser_targets(
        self,
        targets: list[ReputationMappingTarget],
        output_dir: Path,
        *,
        force_capture: bool = False,
        timeout_seconds: int | None = None,
        on_result: Callable[
            [int, ReputationMappingTarget, ReputationPageResult | Exception], None
        ]
        | None = None,
    ) -> list[ReputationPageResult | Exception]:
        """只为指定目标启动浏览器，并在单项终态后立即回传结果。"""

        if not targets:
            return []
        semaphore = asyncio.Semaphore(self.concurrency)
        auth_failed = asyncio.Event()
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(
                headless=self.headless,
                args=browser_launch_args(),
            )

            async def bounded(
                index: int, target: ReputationMappingTarget
            ) -> ReputationPageResult | Exception:
                async with semaphore:
                    await self._acquire_global_slot()
                    try:
                        if auth_failed.is_set():
                            result: ReputationPageResult | Exception = ReputationAdapterError(
                                "AUTH_REQUIRED", "懂车帝共享Session需要更新。"
                            )
                        else:
                            try:
                                result = await self._visit(
                                    browser,
                                    target,
                                    output_dir,
                                    force_capture=force_capture,
                                )
                            except Exception as error:
                                if (
                                    isinstance(error, ReputationAdapterError)
                                    and error.code == "AUTH_REQUIRED"
                                ):
                                    auth_failed.set()
                                result = error
                    finally:
                        self._release_global_slot()
                if on_result:
                    on_result(index, target, result)
                return result

            tasks = [
                asyncio.create_task(bounded(index, target))
                for index, target in enumerate(targets)
            ]
            try:
                done, pending = await asyncio.wait(
                    tasks,
                    timeout=timeout_seconds or self.batch_timeout_seconds,
                    return_when=asyncio.ALL_COMPLETED,
                )
                for task in pending:
                    task.cancel()
                if pending:
                    await asyncio.gather(*pending, return_exceptions=True)
                timeout_error = ReputationAdapterError(
                    "REPUTATION_BATCH_TIMEOUT",
                    "口碑巡检达到45分钟批次上限，未完成项已停止。",
                )
                if on_result:
                    for index, task in enumerate(tasks):
                        if task not in done:
                            on_result(index, targets[index], timeout_error)
                return [task.result() if task in done else timeout_error for task in tasks]
            finally:
                await browser.close()

    async def _validate_http_first(
        self,
        targets: list[ReputationMappingTarget],
        output_dir: Path,
        on_result: Callable[
            [int, ReputationMappingTarget, ReputationPageResult | Exception], None
        ]
        | None = None,
    ) -> list[ReputationPageResult | Exception]:
        """并发轻量取数并完成比较，只把命中证据规则的项交给浏览器。"""

        deadline = time.monotonic() + self.batch_timeout_seconds
        semaphore = asyncio.Semaphore(self.concurrency)
        auth_failed = asyncio.Event()

        async def bounded(target: ReputationMappingTarget) -> ReputationPageResult | Exception:
            async with semaphore:
                await self._acquire_global_slot()
                try:
                    if auth_failed.is_set():
                        return ReputationAdapterError("AUTH_REQUIRED", "懂车帝共享Session需要更新。")
                    try:
                        return await asyncio.to_thread(self._visit_http, target)
                    except Exception as error:
                        if isinstance(error, ReputationAdapterError) and error.code == "AUTH_REQUIRED":
                            auth_failed.set()
                        return error
                finally:
                    self._release_global_slot()

        tasks = [asyncio.create_task(bounded(target)) for target in targets]
        done, pending = await asyncio.wait(
            tasks,
            timeout=self.batch_timeout_seconds,
            return_when=asyncio.ALL_COMPLETED,
        )
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        timeout_error = ReputationAdapterError(
            "REPUTATION_BATCH_TIMEOUT",
            "口碑巡检达到45分钟批次上限，未完成项已停止。",
        )
        results: list[ReputationPageResult | Exception] = [
            task.result() if task in done else timeout_error for task in tasks
        ]
        capture_indexes = [
            index
            for index, (target, result) in enumerate(zip(targets, results, strict=True))
            if isinstance(result, ReputationPageResult)
            and (
                self.evidence_policy is None
                or self.evidence_policy(target, result.measurements[-1])
            )
        ]
        capture_index_set = set(capture_indexes)
        if on_result:
            for index, (target, result) in enumerate(zip(targets, results, strict=True)):
                if index not in capture_index_set:
                    on_result(index, target, result)
        if not capture_indexes:
            return results

        remaining = max(1, int(deadline - time.monotonic()))
        browser_results = await self._validate_browser_targets(
            [targets[index] for index in capture_indexes],
            output_dir,
            force_capture=True,
            timeout_seconds=remaining,
            on_result=(
                lambda local_index, _target, result: on_result(
                    capture_indexes[local_index],
                    targets[capture_indexes[local_index]],
                    result,
                )
                if on_result
                else None
            ),
        )
        for index, browser_result in zip(capture_indexes, browser_results, strict=True):
            results[index] = browser_result
        return results

    async def validate(
        self,
        targets: list[ReputationMappingTarget],
        output_dir: Path,
        on_result: Callable[
            [int, ReputationMappingTarget, ReputationPageResult | Exception], None
        ]
        | None = None,
    ) -> list[ReputationPageResult | Exception]:
        """按输入顺序返回结果；HTTP与页面池并发都不影响持久化顺序。"""

        output_dir.mkdir(parents=True, exist_ok=False)
        if self.prefer_http_first:
            return await self._validate_http_first(targets, output_dir, on_result=on_result)
        return await self._validate_browser_targets(targets, output_dir, on_result=on_result)

    def validate_sync(
        self,
        targets: list[ReputationMappingTarget],
        output_dir: Path,
        on_result: Callable[
            [int, ReputationMappingTarget, ReputationPageResult | Exception], None
        ]
        | None = None,
    ) -> list[ReputationPageResult | Exception]:
        """供FastAPI同步路由和CLI调用的薄同步边界。"""

        return asyncio.run(self.validate(targets, output_dir, on_result=on_result))


def final_url_series_id(url: str) -> str | None:
    """从最终URL提取稳定车型ID，便于测试和审计。"""

    match = SERIES_URL_RE.match(url)
    if match:
        return match.group("id")
    path = urlsplit(url).path
    fallback = re.search(r"/auto/series/(?:score/)?(\d+)", path)
    return fallback.group(1) if fallback else None
