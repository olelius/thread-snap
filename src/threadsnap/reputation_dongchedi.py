"""懂车帝口碑页面的真实浏览器适配器。"""

from __future__ import annotations

import asyncio
import hashlib
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

from patchright.async_api import Browser, Page, async_playwright
from PIL import Image

from .browser_runtime import browser_launch_args

ADAPTER_VERSION = "dongchedi-reputation-v2-region-only"
VALIDATION_CONTRACT_VERSION = "dongchedi-reputation-mapping-v1"
VIEWPORT = {"width": 1440, "height": 1000}
SERIES_URL_RE = re.compile(
    r"^https://www\.dongchedi\.com/auto/series/(?:score/)?(?P<id>\d+)(?:-x-x-x-x-x)?/?(?:\?.*)?$"
)
VOLUME_RE = re.compile(r"共\s*([0-9,]+)\s*人评价")


class ReputationAdapterError(RuntimeError):
    """携带稳定阶段错误码的真实页面验证失败。"""

    def __init__(self, code: str, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


@dataclass(frozen=True)
class ReputationMappingTarget:
    """一次真实页面验证所需的冻结车型映射。"""

    vehicle_id: str
    platform_vehicle_id: str
    platform_url: str
    platform_display_name: str
    mapping_hash: str


@dataclass(frozen=True)
class ReputationPageResult:
    """一次页面上下文完整通过三门禁后的真实结果。"""

    vehicle_id: str
    platform_vehicle_id: str
    mapping_hash: str
    final_url: str
    actual_name: str
    score_raw: str | None
    rank_raw: str | None
    volume_raw: str | None
    rank_scope: str
    measurements: list[dict[str, Any]]
    full_page_path: Path | None
    metric_region_path: Path | None
    full_page_sha256: str | None
    metric_region_sha256: str | None
    width: int
    height: int
    metric_rect: dict[str, float]
    duration_ms: int


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
        for key in ("heading_box", "score_box", "volume_box", "rank_box")
        if isinstance((value := measurement.get(key)), dict)
    ]
    if not boxes:
        raise ReputationAdapterError(
            "REPUTATION_EVIDENCE_REGION_MISSING",
            "页面身份与指标区域没有形成可截图的稳定边界。",
        )
    left = max(0.0, min(float(item["x"]) for item in boxes) - 20)
    top = max(0.0, min(float(item["y"]) for item in boxes) - 20)
    right = max(float(item["x"]) + float(item["width"]) for item in boxes) + 20
    bottom = max(float(item["y"]) + float(item["height"]) for item in boxes) + 20
    return {"x": left, "y": top, "width": right - left, "height": bottom - top}


class DongchediReputationAdapter:
    """用一个有头Chromium和有界页面池验证懂车帝口碑映射。"""

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
    ) -> None:
        self.storage_state = storage_state
        self.concurrency = max(1, min(int(concurrency), 8))
        self.headless = headless
        self.timeout_seconds = timeout_seconds
        self.batch_timeout_seconds = max(1, int(batch_timeout_seconds))
        self.evidence_policy = evidence_policy

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
              const rankScope = rankRoot ? '同级车评分' : '同级车评分';
              const scoreHero = [...document.querySelectorAll('.tw-text-common-yellow')]
                .find((e) => visible(e) && /^\\d+(?:\\.\\d+)?$/.test(text(e)));
              return {
                actual_name: actualName,
                score_raw: scoreText && scoreText !== '-' ? scoreText : null,
                rank_raw: scoreText && scoreText !== '-' && current
                  ? String(rows.indexOf(current) + 1) : null,
                volume_raw: volumeText || null,
                rank_scope: rankScope,
                heading_box: box(heading),
                score_box: box(scoreHero),
                volume_box: box(volumeNode),
                rank_box: box(rankRoot),
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
            value.get("rank_scope"),
            rounded_box("heading_box"),
            rounded_box("score_box"),
            rounded_box("volume_box"),
            rounded_box("rank_box"),
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

    async def _visit(
        self,
        browser: Browser,
        target: ReputationMappingTarget,
        output_dir: Path,
    ) -> ReputationPageResult:
        started = time.monotonic()
        context = await browser.new_context(
            storage_state=self.storage_state,
            viewport=VIEWPORT,
            device_scale_factor=1,
            locale="zh-CN",
        )
        page = await context.new_page()
        page.set_default_timeout(self.timeout_seconds * 1000)
        try:
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
            await page.locator("h1:visible").first.wait_for(state="visible", timeout=15_000)
            if "/login-required" in page.url:
                raise ReputationAdapterError("AUTH_REQUIRED", "懂车帝共享Session需要更新。")
            await page.wait_for_timeout(1800)
            await self._freeze_layout(page)
            measurements: list[dict[str, Any]] = []
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
            capture = self.evidence_policy is None or self.evidence_policy(target, current)
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
            )
        finally:
            await context.close()

    async def validate(
        self,
        targets: list[ReputationMappingTarget],
        output_dir: Path,
    ) -> list[ReputationPageResult | Exception]:
        """按输入顺序返回结果；页面池并发不影响持久化顺序。"""

        output_dir.mkdir(parents=True, exist_ok=False)
        semaphore = asyncio.Semaphore(self.concurrency)
        auth_failed = asyncio.Event()
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(
                headless=self.headless,
                args=browser_launch_args(),
            )

            async def bounded(target: ReputationMappingTarget) -> ReputationPageResult | Exception:
                async with semaphore:
                    if auth_failed.is_set():
                        return ReputationAdapterError(
                            "AUTH_REQUIRED", "懂车帝共享Session需要更新。"
                        )
                    try:
                        return await self._visit(browser, target, output_dir)
                    except Exception as error:
                        if isinstance(error, ReputationAdapterError) and error.code == "AUTH_REQUIRED":
                            auth_failed.set()
                        return error

            tasks = [asyncio.create_task(bounded(target)) for target in targets]
            try:
                done, pending = await asyncio.wait(
                    tasks, timeout=self.batch_timeout_seconds, return_when=asyncio.ALL_COMPLETED
                )
                for task in pending:
                    task.cancel()
                if pending:
                    await asyncio.gather(*pending, return_exceptions=True)
                timeout_error = ReputationAdapterError(
                    "REPUTATION_BATCH_TIMEOUT",
                    "口碑巡检达到45分钟批次上限，未完成项已停止。",
                )
                return [
                    task.result() if task in done else timeout_error for task in tasks
                ]
            finally:
                await browser.close()

    def validate_sync(
        self,
        targets: list[ReputationMappingTarget],
        output_dir: Path,
    ) -> list[ReputationPageResult | Exception]:
        """供FastAPI同步路由和CLI调用的薄同步边界。"""

        return asyncio.run(self.validate(targets, output_dir))


def final_url_series_id(url: str) -> str | None:
    """从最终URL提取稳定车型ID，便于测试和审计。"""

    match = SERIES_URL_RE.match(url)
    if match:
        return match.group("id")
    path = urlsplit(url).path
    fallback = re.search(r"/auto/series/(?:score/)?(\d+)", path)
    return fallback.group(1) if fallback else None
