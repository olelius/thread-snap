"""懂车帝口碑页面的轻量取数与按需浏览器证据适配器。"""

from __future__ import annotations

import asyncio
import hashlib
import re
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

from curl_cffi import requests
from curl_cffi.requests import Cookies
from lxml import html
from patchright.async_api import Browser, Page, async_playwright
from PIL import Image

from .browser_runtime import browser_launch_args

ADAPTER_VERSION = "dongchedi-reputation-v5-circle-content"
VALIDATION_CONTRACT_VERSION = "dongchedi-reputation-mapping-v1"
VIEWPORT = {"width": 1440, "height": 1000}
SERIES_URL_RE = re.compile(
    r"^https://www\.dongchedi\.com/auto/series/(?:score/)?(?P<id>\d+)(?:-x-x-x-x-x)?/?(?:\?.*)?$"
)
VOLUME_RE = re.compile(r"共\s*([0-9,]+)\s*人评价")
CIRCLE_CONTENT_RE = re.compile(r"共\s*([0-9,]+)\s*条内容")
CIRCLE_PATH_RE = re.compile(r"^/community/(?P<id>\d+)/?$")


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
    """一次轻量响应或浏览器页面完整通过身份与指标门禁后的真实结果。"""

    vehicle_id: str
    platform_vehicle_id: str
    mapping_hash: str
    final_url: str
    actual_name: str
    score_raw: str | None
    rank_raw: str | None
    volume_raw: str | None
    circle_content_raw: str | None
    circle_url: str | None
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


def _cookies_from_state(state: dict[str, Any] | None) -> Cookies:
    """把浏览器 storage state 中仍有效的懂车帝 Cookie 转成 HTTP CookieJar。"""

    jar = Cookies()
    now = time.time()
    for item in (state or {}).get("cookies", []):
        if not isinstance(item, dict):
            continue
        domain = str(item.get("domain") or "")
        expires = item.get("expires", -1)
        if "dongchedi.com" not in domain:
            continue
        if isinstance(expires, (int, float)) and expires > 0 and expires <= now:
            continue
        if all(item.get(key) for key in ("name", "value", "path")):
            jar.set(
                str(item["name"]),
                str(item["value"]),
                domain=domain,
                path=str(item["path"]),
                secure=bool(item.get("secure")),
            )
    return jar


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
        include_circle_content: bool = False,
    ) -> None:
        self.storage_state = storage_state
        self.concurrency = max(1, min(int(concurrency), 8))
        self.headless = headless
        self.timeout_seconds = timeout_seconds
        self.batch_timeout_seconds = max(1, int(batch_timeout_seconds))
        self.evidence_policy = evidence_policy
        self.prefer_http_first = prefer_http_first
        self.include_circle_content = include_circle_content
        self.cookies = _cookies_from_state(storage_state)
        self._thread_local = threading.local()

    def _http_session(self) -> requests.Session:
        """每个取数线程独享 Session，避免跨线程共享可变请求状态。"""

        session = getattr(self._thread_local, "http", None)
        if session is None:
            session = requests.Session(impersonate="chrome")
            session.cookies.update(self.cookies)
            self._thread_local.http = session
        return session

    def _visit_circle_content(self, target: ReputationMappingTarget) -> tuple[str, str]:
        """通过同一平台车型ID直接读取圈子内容总量，不启动额外浏览器页面。"""

        circle_url = f"https://www.dongchedi.com/community/{target.platform_vehicle_id}"
        try:
            response = self._http_session().get(
                circle_url,
                timeout=self.timeout_seconds,
                allow_redirects=True,
            )
        except Exception as error:
            raise ReputationAdapterError(
                "REPUTATION_CIRCLE_NETWORK_ERROR",
                f"直接访问车型圈子页面失败：{error}",
                retryable=True,
            ) from error
        final_url = str(response.url)
        body = bytes(response.content or b"")
        if "/login-required" in urlsplit(final_url).path or b"login-required" in body[:200_000].lower():
            raise ReputationAdapterError("AUTH_REQUIRED", "懂车帝共享Session需要更新。")
        if response.status_code >= 500 or response.status_code == 429:
            raise ReputationAdapterError(
                "REPUTATION_CIRCLE_SERVER_ERROR",
                f"车型圈子页面返回HTTP {response.status_code}。",
                retryable=True,
            )
        if response.status_code >= 400:
            raise ReputationAdapterError(
                "REPUTATION_CIRCLE_STATUS_ERROR",
                f"车型圈子页面返回HTTP {response.status_code}。",
            )
        final_path = urlsplit(final_url).path
        circle_match = CIRCLE_PATH_RE.match(final_path)
        if not circle_match or circle_match.group("id") != target.platform_vehicle_id:
            raise ReputationAdapterError(
                "REPUTATION_CIRCLE_IDENTITY_REDIRECT",
                "圈子页面跳转后的稳定车型ID与口碑巡检车型ID不一致。",
            )
        if not body:
            raise ReputationAdapterError(
                "REPUTATION_CIRCLE_DOCUMENT_EMPTY",
                "车型圈子页面返回空文档。",
                retryable=True,
            )
        try:
            document = html.fromstring(body.decode("utf-8"))
            text = " ".join(document.text_content().split())
        except (TypeError, UnicodeDecodeError, ValueError) as error:
            raise ReputationAdapterError(
                "REPUTATION_CIRCLE_DOCUMENT_INVALID",
                "车型圈子页面没有返回可解析的HTML文档。",
                retryable=True,
            ) from error
        match = CIRCLE_CONTENT_RE.search(text)
        if not match:
            raise ReputationAdapterError(
                "REPUTATION_CIRCLE_CONTENT_MISSING",
                "车型圈子页面未返回可识别的内容总量。",
                retryable=True,
            )
        return match.group(1).replace(",", ""), circle_url

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
        *,
        force_capture: bool = False,
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
            circle_content_raw: str | None = None
            circle_url: str | None = None
            if self.include_circle_content:
                circle_content_raw, circle_url = await asyncio.to_thread(
                    self._visit_circle_content, target
                )
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
                circle_content_raw=circle_content_raw,
                circle_url=circle_url,
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

    @staticmethod
    def _node_text(node: Any) -> str:
        """读取 SSR 节点的可见文本，并折叠布局空白。"""

        return " ".join(str(node.text_content()).split())

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
        measurement = {
            "actual_name": actual_name,
            "score_raw": score_raw,
            "rank_raw": rank_raw,
            "volume_raw": volume_text,
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
            circle_content_raw=None,
            circle_url=None,
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
        if not self.include_circle_content:
            return result
        circle_content_raw, circle_url = self._visit_circle_content(target)
        return replace(
            result,
            circle_content_raw=circle_content_raw,
            circle_url=circle_url,
            duration_ms=round((time.monotonic() - started) * 1000),
        )

    async def _validate_browser_targets(
        self,
        targets: list[ReputationMappingTarget],
        output_dir: Path,
        *,
        force_capture: bool = False,
        timeout_seconds: int | None = None,
    ) -> list[ReputationPageResult | Exception]:
        """只为指定目标启动浏览器；正式日检传入的就是已判定需截图项。"""

        if not targets:
            return []
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
                        return await self._visit(
                            browser,
                            target,
                            output_dir,
                            force_capture=force_capture,
                        )
                    except Exception as error:
                        if isinstance(error, ReputationAdapterError) and error.code == "AUTH_REQUIRED":
                            auth_failed.set()
                        return error

            tasks = [asyncio.create_task(bounded(target)) for target in targets]
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
                return [task.result() if task in done else timeout_error for task in tasks]
            finally:
                await browser.close()

    async def _validate_http_first(
        self,
        targets: list[ReputationMappingTarget],
        output_dir: Path,
    ) -> list[ReputationPageResult | Exception]:
        """并发轻量取数并完成比较，只把命中证据规则的项交给浏览器。"""

        deadline = time.monotonic() + self.batch_timeout_seconds
        semaphore = asyncio.Semaphore(self.concurrency)
        auth_failed = asyncio.Event()

        async def bounded(target: ReputationMappingTarget) -> ReputationPageResult | Exception:
            async with semaphore:
                if auth_failed.is_set():
                    return ReputationAdapterError("AUTH_REQUIRED", "懂车帝共享Session需要更新。")
                try:
                    return await asyncio.to_thread(self._visit_http, target)
                except Exception as error:
                    if isinstance(error, ReputationAdapterError) and error.code == "AUTH_REQUIRED":
                        auth_failed.set()
                    return error

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
        if not capture_indexes:
            return results

        remaining = max(1, int(deadline - time.monotonic()))
        browser_results = await self._validate_browser_targets(
            [targets[index] for index in capture_indexes],
            output_dir,
            force_capture=True,
            timeout_seconds=remaining,
        )
        for index, browser_result in zip(capture_indexes, browser_results, strict=True):
            results[index] = browser_result
        return results

    async def validate(
        self,
        targets: list[ReputationMappingTarget],
        output_dir: Path,
    ) -> list[ReputationPageResult | Exception]:
        """按输入顺序返回结果；HTTP与页面池并发都不影响持久化顺序。"""

        output_dir.mkdir(parents=True, exist_ok=False)
        if self.prefer_http_first:
            return await self._validate_http_first(targets, output_dir)
        return await self._validate_browser_targets(targets, output_dir)

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
