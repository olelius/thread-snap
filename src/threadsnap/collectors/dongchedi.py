"""懂车帝动态圈子、帖子详情和一级评论适配器。"""

from __future__ import annotations

import base64
import binascii
import json
import math
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Callable, Iterable
from urllib.parse import urlencode, urljoin, urlsplit

from curl_cffi import requests
from curl_cffi.requests import Cookies
from lxml import html
from patchright.sync_api import sync_playwright
from scrapling.fetchers import DynamicSession

from ..browser_runtime import browser_launch_args
from .base import AuthenticationRequired, CircleSource, CollectorFailure

ADAPTER_VERSION = "dongchedi-dynamic-v4"
BASE_URL = "https://www.dongchedi.com"
DETAIL_ROOT = f"{BASE_URL}/motor/pc/ugc/detail"
VIDEO_TOKEN_URL = f"{BASE_URL}/motor/pc/common/token"
VIDEO_PLAY_INFO_URL = "https://vod.bytedanceapi.com/"
COMMON_PARAMS = {"aid": "1839", "app_name": "auto_web_pc"}
CIRCLE_RE = re.compile(
    r"^https?://(?:www\.)?dongchedi\.com/community/(?P<id>\d+)"
    r"(?:/(?:(?P<feed>dongtai-release)(?:/(?P<feed_page>\d+))?|(?P<page>\d+)))?"
    r"/?(?:\?.*)?$"
)
POST_RE = re.compile(
    r"^https?://(?:www\.)?dongchedi\.com/(?:ugc/)?article/(?P<id>\d+)(?:[/?#].*)?$"
)
SORT_LABEL_RE = re.compile(r"(?:\d{4}-\d{2}-\d{2}|\d+(?:分钟|小时|天|个月|年)前)(?:回复)?")
VISIBLE_OPERATION_STATUSES = frozenset({0, 2})
ProgressCallback = Callable[[dict[str, Any] | None, dict[str, Any] | None], None]
PageEvidenceCallback = Callable[[dict[str, Any]], None]
RICH_TEXT_TAG_RE = re.compile(
    r"<(?:article|blockquote|br|div|h[1-6]|img|li|ol|p|section|ul)\b",
    re.IGNORECASE,
)
BLOCK_END_TAG_RE = re.compile(
    r"</(?:article|blockquote|div|h[1-6]|li|ol|p|section|ul)>",
    re.IGNORECASE,
)
BREAK_TAG_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)


def parse_circle_url(url: str) -> CircleSource:
    """识别最新回复或最新发布入口，并移除页码和查询参数。"""

    match = CIRCLE_RE.match(url.strip())
    if not match:
        raise CollectorFailure(
            "CIRCLE_URL_INVALID",
            "圈子链接格式无效，必须是懂车帝 community 的最新回复或最新发布链接。",
        )
    circle_id = match.group("id")
    latest_publish = match.group("feed") == "dongtai-release"
    list_order = "latest_publish" if latest_publish else "latest_reply"
    suffix = "/dongtai-release" if latest_publish else ""
    return CircleSource(circle_id, f"{BASE_URL}/community/{circle_id}{suffix}", list_order)


def normalize_circle_url(url: str) -> tuple[str, str]:
    source = parse_circle_url(url)
    return source.external_id, source.url


def normalize_post_url(url: str) -> tuple[str, str]:
    match = POST_RE.match(url.strip())
    if not match:
        raise CollectorFailure("POST_URL_INVALID", "帖子链接格式无效，必须是懂车帝文章链接。")
    post_id = match.group("id")
    return post_id, f"{BASE_URL}/ugc/article/{post_id}"


def _cookies_from_state(state: dict[str, Any] | None) -> Cookies:
    jar = Cookies()
    now = time.time()
    for item in (state or {}).get("cookies", []):
        if not isinstance(item, dict):
            continue
        domain = str(item.get("domain") or "")
        if "dongchedi.com" not in domain:
            continue
        expires = item.get("expires", -1)
        if isinstance(expires, (int, float)) and expires > 0 and expires <= now:
            continue
        if all(item.get(key) for key in ("name", "value", "path")):
            jar.set(
                item["name"],
                item["value"],
                domain=domain,
                path=item["path"],
                secure=bool(item.get("secure")),
            )
    return jar


def _iso_time(value: object) -> datetime | None:
    try:
        timestamp = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None
    if timestamp <= 0:
        return None
    try:
        return datetime.fromtimestamp(timestamp, tz=timezone.utc)
    except (OSError, OverflowError, ValueError):
        return None


def _unique_urls(values: Iterable[object]) -> list[str]:
    output: list[str] = []
    for value in values:
        if (
            isinstance(value, str)
            and value.startswith(("http://", "https://"))
            and value not in output
        ):
            output.append(value)
    return output


def _first_sentence(text: str) -> str | None:
    for value in re.split(r"(?<=[。！？!?])|\r?\n+", text):
        if value.strip():
            return value.strip()
    return None


def _plain_text(value: object) -> str:
    """把平台富文本正文转换为保留段落顺序的纯文本。"""

    raw = str(value or "").strip()
    if not raw:
        return ""
    if not RICH_TEXT_TAG_RE.search(raw):
        return "\n".join(
            line
            for line in (
                re.sub(r"[\t\f\v ]+", " ", item).strip()
                for item in raw.replace("\xa0", " ").splitlines()
            )
            if line
        )
    prepared = BREAK_TAG_RE.sub("\n", raw)
    prepared = BLOCK_END_TAG_RE.sub(lambda match: f"{match.group(0)}\n", prepared)
    try:
        document = html.fromstring(f"<div>{prepared}</div>")
        for element in document.xpath(".//script|.//style"):
            element.drop_tree()
        text = document.text_content()
    except (TypeError, ValueError):
        text = re.sub(r"<[^>]+>", " ", prepared)
    return "\n".join(
        line
        for line in (
            re.sub(r"[\t\f\v ]+", " ", item).strip()
            for item in text.replace("\xa0", " ").splitlines()
        )
        if line
    )


class DongchediCollector:
    """单实例可由同一平台多个圈子任务共享请求并发信号量。"""

    code = "dongchedi"
    display_name = "懂车帝"
    adapter_version = ADAPTER_VERSION
    supports_page_evidence = True
    supports_live_video_resolution = True

    def __init__(
        self,
        storage_state: dict[str, Any] | None,
        concurrency: int = 1,
        timeout_seconds: int = 30,
        browser_headless: bool = False,
    ):
        self.storage_state = storage_state
        self.cookies = _cookies_from_state(storage_state)
        self.timeout_seconds = timeout_seconds
        self.concurrency = max(1, concurrency)
        self.browser_headless = browser_headless
        self.semaphore = threading.BoundedSemaphore(self.concurrency)
        self.page_capture_lock = threading.Lock()
        self._thread_local = threading.local()

    def _http_session(self) -> requests.Session:
        """为每个采集线程创建独立 HTTP Session，避免跨线程共享可变请求状态。"""

        session = getattr(self._thread_local, "http", None)
        if session is None:
            session = requests.Session(impersonate="chrome")
            session.cookies.update(self.cookies)
            self._thread_local.http = session
        return session

    def _get(self, url: str) -> requests.Response:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                with self.semaphore:
                    response = self._http_session().get(
                        url, timeout=self.timeout_seconds, allow_redirects=True
                    )
                if response.status_code >= 500 and attempt < 2:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                return response
            except Exception as exc:  # curl_cffi 抛出多种传输异常，统一有界重试。
                last_error = exc
                if attempt < 2:
                    time.sleep(0.5 * (attempt + 1))
        raise CollectorFailure("PLATFORM_NETWORK_ERROR", f"访问懂车帝失败：{last_error}")

    @staticmethod
    def _detect_auth(response: requests.Response) -> None:
        path = urlsplit(str(response.url)).path
        body = response.content[:200_000].lower()
        content_type = str(getattr(response, "headers", {}).get("content-type", "")).lower()
        is_html = "html" in content_type or body.lstrip().startswith((b"<!doctype html", b"<html"))
        if "/login-required" in path or is_html and b"login-required" in body:
            raise AuthenticationRequired("懂车帝当前要求重新完成平台认证。")

    def _browser_page_rows(self, url: str) -> list[dict[str, Any]]:
        state: dict[str, Any] = {}
        cookie_items = [
            item for item in (self.storage_state or {}).get("cookies", []) if isinstance(item, dict)
        ]

        def action(page: Any) -> None:
            page.wait_for_timeout(1500)
            state["url"] = page.url
            state["rows"] = page.locator("section.community-card").evaluate_all(
                "els => els.map((e,i) => ({index:i,text:(e.innerText||''),hrefs:Array.from(e.querySelectorAll('a')).map(a=>a.href)}))"
            )

        with self.semaphore:
            with DynamicSession(
                headless=True,
                real_chrome=True,
                google_search=False,
                max_pages=1,
                timeout=self.timeout_seconds * 1000,
                retries=1,
                cookies=cookie_items or None,
                disable_resources=True,
            ) as browser:
                browser.fetch(url, page_action=action, wait=500, network_idle=False)
        if "/login-required" in str(state.get("url", "")):
            raise AuthenticationRequired("懂车帝当前要求重新完成平台认证。")
        return self._normalize_card_rows(state.get("rows", []))

    @staticmethod
    def _stabilize_capture_layout(page: Any, cards: Any, page_number: int) -> None:
        """回到页首并等待平台原始布局稳定，不向页面注入样式。"""

        page.evaluate(
            """() => {
              window.scrollTo({top:0,left:0,behavior:'instant'});
              document.documentElement.scrollTop=0;
              document.documentElement.scrollLeft=0;
              if (document.body) {
                document.body.scrollTop=0;
                document.body.scrollLeft=0;
              }
            }"""
        )
        page.wait_for_function("() => scrollX === 0 && scrollY === 0")
        # 懒加载遍历结束时页面位于底部。只恢复平台原始页首状态并等待稳定；
        # 不覆盖滚动条、动画、定位或其他页面 CSS，避免改变原图文字和布局。
        previous_layout: list[dict[str, float]] | None = None
        stable_samples = 0
        for _attempt in range(8):
            layout = cards.evaluate_all(
                "els => els.map(e => {const r=e.getBoundingClientRect(); return {x:r.x+scrollX,y:r.y+scrollY,width:r.width,height:r.height,hrefs:Array.from(e.querySelectorAll('a')).map(a=>a.href)}})"
            )
            if layout == previous_layout:
                stable_samples += 1
                if stable_samples >= 2:
                    break
            else:
                stable_samples = 0
            previous_layout = layout
            page.wait_for_timeout(250)
        if stable_samples < 2:
            raise CollectorFailure(
                "PAGE_EVIDENCE_LAYOUT_UNSTABLE",
                f"圈子第 {page_number} 页卡片布局在页首稳定窗口内仍持续变化。",
            )

    def capture_circle_page(self, circle_url: str, page_number: int) -> dict[str, Any]:
        """从同一冻结 DOM 取得候选清单、卡片坐标和原始全页 PNG。"""

        source = parse_circle_url(circle_url)
        exact_url = source.url + ("" if page_number == 1 else f"/{page_number}")
        with self.page_capture_lock, self.semaphore:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    headless=self.browser_headless, args=browser_launch_args()
                )
                context = browser.new_context(
                    storage_state=self.storage_state,
                    locale="zh-CN",
                    timezone_id="Asia/Shanghai",
                    viewport={"width": 1440, "height": 900},
                    device_scale_factor=1,
                )
                browser_version = browser.version
                page = context.new_page()
                page.goto(exact_url, wait_until="domcontentloaded", timeout=60_000)
                page.wait_for_timeout(1200)
                if "/login-required" in page.url:
                    context.close()
                    browser.close()
                    raise AuthenticationRequired("懂车帝当前要求重新完成平台认证。")
                cards = page.locator("section.community-card")
                count = cards.count()
                for index in range(count):
                    card = cards.nth(index)
                    card.scroll_into_view_if_needed(timeout=10_000)
                    try:
                        card.locator("img").evaluate_all(
                            """imgs => Promise.all(imgs.map(img => new Promise(resolve => {
                              const src = img.currentSrc || img.src || '';
                              if (!src || (img.complete && img.naturalWidth > 0)) return resolve();
                              const done = () => resolve();
                              img.addEventListener('load', done, {once:true});
                              img.addEventListener('error', done, {once:true});
                              setTimeout(done, 8000);
                            })))"""
                        )
                    except Exception:
                        # 平台原生占位或已被平台取消的媒体不阻断页面文字证据。
                        pass
                page.evaluate("() => document.fonts && document.fonts.ready")
                media_state = cards.evaluate_all(
                    """els => els.flatMap((card, cardIndex) =>
                      Array.from(card.querySelectorAll('img')).map(img => ({
                        cardIndex, src:img.currentSrc||img.src||'', complete:img.complete,
                        naturalWidth:img.naturalWidth, naturalHeight:img.naturalHeight
                      })))"""
                )
                incomplete = [
                    item
                    for item in media_state
                    if not item.get("src")
                    or not item.get("complete")
                    or int(item.get("naturalWidth") or 0) <= 0
                    or int(item.get("naturalHeight") or 0) <= 0
                ]
                if incomplete:
                    raise CollectorFailure(
                        "PAGE_EVIDENCE_MEDIA_INCOMPLETE",
                        f"圈子第 {page_number} 页仍有 {len(incomplete)} 个帖子媒体处于空白、加载或破图状态。",
                    )
                self._stabilize_capture_layout(page, cards, page_number)
                raw_rows = cards.evaluate_all(
                    """els => els.map((e, i) => {
                      const r=e.getBoundingClientRect();
                      return {index:i,text:e.innerText||'',
                        hrefs:Array.from(e.querySelectorAll('a')).map(a=>a.href),
                        image_count:e.querySelectorAll('img').length,
                        rect:{x:r.x+scrollX,y:r.y+scrollY,width:r.width,height:r.height}};
                    })"""
                )
                normalized = self._normalize_card_rows(raw_rows)
                by_index = {int(item.get("index", -1)): item for item in raw_rows}
                rows = []
                for item in normalized:
                    raw = by_index.get(int(item["order_index"]), {})
                    rows.append(
                        {
                            **item,
                            "text": raw.get("text") or "",
                            "image_count": int(raw.get("image_count") or 0),
                            "rect": raw.get("rect") or {},
                        }
                    )
                document = page.evaluate(
                    "() => ({width:Math.max(document.documentElement.scrollWidth,document.body.scrollWidth),height:Math.max(document.documentElement.scrollHeight,document.body.scrollHeight)})"
                )
                screenshot = page.screenshot(full_page=True, type="png")
                final_url = page.url
                context.close()
                browser.close()
        return {
            "page_number": page_number,
            "exact_url": final_url,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "adapter_version": self.adapter_version,
            "browser_version": browser_version,
            "viewport": {"width": 1440, "height": 900, "device_scale_factor": 1},
            "document": document,
            "rows": rows,
            "screenshot": screenshot,
        }

    @staticmethod
    def _normalize_card_rows(
        raw_rows: Iterable[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for raw in raw_rows:
            post_id = None
            for href in raw.get("hrefs", []):
                normalized_href = urljoin(BASE_URL, str(href)).split("#", 1)[0]
                match = POST_RE.match(normalized_href)
                if match:
                    post_id = match.group("id")
                    break
            if not post_id:
                continue
            text = str(raw.get("text") or "")
            labels = SORT_LABEL_RE.findall(text)
            rows.append(
                {
                    "post_id": post_id,
                    "url": f"{BASE_URL}/ugc/article/{post_id}",
                    "sort_label": labels[-1] if labels else None,
                    "order_index": int(raw.get("index", len(rows))),
                }
            )
        return rows

    def _fetch_circle_page(
        self, circle_url: str, page: int, expected_count: int | None
    ) -> dict[str, Any]:
        source = parse_circle_url(circle_url)
        url = source.url + ("" if page == 1 else f"/{page}")
        response = self._get(url)
        self._detect_auth(response)
        if response.status_code != 200:
            raise CollectorFailure(
                "CIRCLE_PAGE_ERROR",
                f"圈子第 {page} 页返回 HTTP {response.status_code}。",
            )
        document = html.fromstring(response.content)
        title = document.xpath("string(//title)")
        body = document.text_content()
        raw_rows = []
        for index, card in enumerate(document.cssselect("section.community-card")):
            raw_rows.append(
                {
                    "index": index,
                    "text": " ".join(
                        value.strip() for value in card.xpath(".//text()") if value.strip()
                    ),
                    "hrefs": card.xpath(".//a/@href"),
                }
            )
        total_match = re.search(r"共\s*(\d+)\s*条内容", body)
        page_match = re.search(r"_(\d+)/(\d+)页_", title)
        name_match = re.search(r"^(.*?)车友圈", title)
        total_count = int(total_match.group(1)) if total_match else None
        page_count = int(page_match.group(2)) if page_match else None
        rows = self._normalize_card_rows(raw_rows)
        # 首页请求时尚不知总数，解析后再推导该页应有数量，避免 SSR 残缺被误当成完整列表。
        effective_expected = expected_count
        if effective_expected is None and total_count is not None:
            effective_expected = min(30, max(0, total_count - (page - 1) * 30))
        if effective_expected is not None and len(rows) < effective_expected:
            rows = self._browser_page_rows(url)
        return {
            "url": url,
            "title": title,
            "circle_name": f"{name_match.group(1)}车友圈" if name_match else None,
            "total_count": total_count,
            "page_count": page_count,
            "rows": rows,
        }

    def validate_circle(self, circle_url: str) -> dict[str, Any]:
        source = parse_circle_url(circle_url)
        page = self._fetch_circle_page(source.url, 1, expected_count=None)
        if not page["circle_name"] or not page["rows"]:
            raise CollectorFailure("CIRCLE_VALIDATION_FAILED", "圈子页面未返回可识别的动态帖子。")
        record = self.fetch_post(page["rows"][0]["url"])
        if record is None:
            raise CollectorFailure("CIRCLE_VALIDATION_FAILED", "圈子首条帖子未返回有效详情。")
        return {
            "platform_code": self.code,
            "external_id": source.external_id,
            "name": page["circle_name"],
            "url": source.url,
            "section": "dynamic",
            "sort": source.list_order,
            "sample_post_id": record["platform_post_id"],
            "adapter_version": self.adapter_version,
        }

    def discover_posts(
        self, circle_url: str, target_count: int, start_page: int = 1
    ) -> tuple[list[dict[str, Any]], str]:
        source = parse_circle_url(circle_url)
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        page_number = max(1, start_page)
        page_count: int | None = None
        total_count: int | None = None
        while len(rows) < target_count:
            expected = None
            if page_count is not None:
                expected = min(30, max(0, (total_count or 0) - (page_number - 1) * 30))
            page = self._fetch_circle_page(source.url, page_number, expected)
            if page_number == 1:
                total_count = page["total_count"]
                page_count = (
                    math.ceil(total_count / 30) if total_count is not None else page["page_count"]
                )
            novel = [item for item in page["rows"] if item["post_id"] not in seen]
            for item in novel:
                seen.add(item["post_id"])
                rows.append(item)
                if len(rows) >= target_count:
                    return rows, "达到配置的有效结果候选数量。"
            if not novel or not page["rows"]:
                return rows, "平台没有返回更多动态内容。"
            if page_count is not None and page_number >= page_count:
                return rows, "已经到达圈子动态列表末页。"
            page_number += 1
        return rows, "达到配置的有效结果候选数量。"

    def _json_api(self, endpoint: str, **params: object) -> tuple[dict[str, Any], int]:
        url = f"{DETAIL_ROOT}/{endpoint}?{urlencode({**COMMON_PARAMS, **params})}"
        response = self._get(url)
        self._detect_auth(response)
        try:
            payload = json.loads(response.content)
        except json.JSONDecodeError as exc:
            raise CollectorFailure(
                "PLATFORM_RESPONSE_INVALID", "懂车帝接口返回了无法识别的数据。"
            ) from exc
        if not isinstance(payload, dict):
            raise CollectorFailure("PLATFORM_RESPONSE_INVALID", "懂车帝接口返回结构无效。")
        message = str(payload.get("message") or payload.get("status_message") or "")
        if payload.get("status") not in (None, 0) and any(
            marker in message.lower() for marker in ("登录", "login")
        ):
            raise AuthenticationRequired("懂车帝当前要求重新完成平台认证。", trigger_url=url)
        return payload, int(response.status_code)

    def fetch_post(self, post_url: str) -> dict[str, Any] | None:
        post_id, normalized_url = normalize_post_url(post_url)
        payload, http_status = self._json_api("common", group_id=post_id)
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        if http_status == 404 or payload.get("status") != 0 or not data:
            return None
        observed = str(data.get("group_id_str") or data.get("group_id") or "")
        if observed != post_id:
            return None
        profile = (
            data.get("motor_profile_info")
            if isinstance(data.get("motor_profile_info"), dict)
            else {}
        )
        car_info = (
            data.get("motor_car_info") if isinstance(data.get("motor_car_info"), dict) else {}
        )
        detail_content = _plain_text(data.get("content"))
        motor_text = _plain_text(data.get("motor_title"))
        thread_title = _plain_text(data.get("thread_title"))
        if detail_content:
            # 富文本文章把短标题放在 motor_title、正文放在 content；普通动态则常把
            # 唯一可见文字放在 motor_title，并让 content 为空。按正文是否存在分流，
            # 避免把普通动态的整段正文误存为标题。
            content = detail_content
            platform_title = thread_title or motor_text
        else:
            content = motor_text
            platform_title = thread_title
        image_items = data.get("image_urls") if isinstance(data.get("image_urls"), list) else []
        images = _unique_urls(
            item.get("url") if isinstance(item, dict) else item for item in image_items
        )
        videos = self._video_urls(data.get("video_play_info"))
        operation_status = data.get("operation_status")
        visibility = "visible" if operation_status in VISIBLE_OPERATION_STATUSES else "unknown"
        comments = self._fetch_comments(post_id, int(data.get("comment_count") or 0))
        return {
            "platform_post_id": post_id,
            "url": normalized_url,
            "title": platform_title or _first_sentence(content),
            "author": str(profile.get("name") or "").strip() or None,
            "published_at": _iso_time(data.get("content_publish_time") or data.get("created_time")),
            "content": content or None,
            "image_urls": images,
            "video_urls": videos,
            "reply_count": data.get("comment_count")
            if isinstance(data.get("comment_count"), int)
            else None,
            "like_count": data.get("digg_count")
            if isinstance(data.get("digg_count"), int)
            else None,
            "section": str(car_info.get("source_desc") or car_info.get("motor_name") or "").strip()
            or None,
            "visibility": visibility,
            "raw_status": {
                "api_status": payload.get("status"),
                "operation_status": operation_status,
                "visibility_level": data.get("visibility_level"),
                "video_id": str(data.get("vid") or "").strip() or None,
            },
            "comments": comments,
        }

    @staticmethod
    def _video_urls(value: object) -> list[str]:
        if isinstance(value, str) and value.strip():
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                return []
        output: list[str] = []

        def walk(item: object, path: str = "") -> None:
            if isinstance(item, dict):
                for key, child in item.items():
                    walk(child, f"{path}.{key}")
            elif isinstance(item, list):
                for child in item:
                    walk(child, path)
            elif (
                isinstance(item, str)
                and item.startswith(("http://", "https://"))
                and any(mark in path.lower() for mark in ("play", "video", "url"))
            ):
                if item not in output:
                    output.append(item)

        walk(value)
        return output

    def resolve_video_urls(self, video_id: str) -> list[str]:
        """使用平台公开网页同款的两段 HTTP 接口解析当前最高画质播放 URL。"""

        normalized_id = str(video_id or "").strip()
        if not normalized_id:
            return []
        token_params = {
            **COMMON_PARAMS,
            "video_id": normalized_id,
            "format_type": "mp4",
        }
        token_url = f"{VIDEO_TOKEN_URL}?{urlencode(token_params)}"
        token_response = self._get(token_url)
        self._detect_auth(token_response)
        if token_response.status_code != 200:
            raise CollectorFailure(
                "VIDEO_TOKEN_ERROR",
                f"懂车帝视频授权接口返回 HTTP {token_response.status_code}。",
            )
        try:
            token_payload = json.loads(token_response.content)
            encoded_token = token_payload["data"]["play_auth_token"]
            decoded_token = json.loads(base64.b64decode(encoded_token, validate=True))
            signed_query = str(decoded_token["GetPlayInfoToken"]).strip()
        except (
            binascii.Error,
            json.JSONDecodeError,
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            raise CollectorFailure(
                "VIDEO_TOKEN_INVALID",
                "懂车帝视频授权接口返回结构无效。",
            ) from exc
        if token_payload.get("status") != 0 or not signed_query:
            raise CollectorFailure(
                "VIDEO_TOKEN_INVALID",
                "懂车帝视频授权接口没有返回有效授权。",
            )

        play_params = urlencode(
            {
                "codec_type": 0,
                "definition": 0,
                "format_type": "mp4",
                "stream_type": "video",
                "video_id": normalized_id,
                "watermark": "unwatermarked",
                "ssl": "true",
                "aid": 36,
            }
        )
        play_response = self._get(f"{VIDEO_PLAY_INFO_URL}?{signed_query}&{play_params}")
        if play_response.status_code != 200:
            raise CollectorFailure(
                "VIDEO_PLAY_INFO_ERROR",
                f"视频播放信息接口返回 HTTP {play_response.status_code}。",
            )
        try:
            play_payload = json.loads(play_response.content)
        except json.JSONDecodeError as exc:
            raise CollectorFailure(
                "VIDEO_PLAY_INFO_INVALID",
                "视频播放信息接口返回结构无效。",
            ) from exc
        result = play_payload.get("Result", {}) if isinstance(play_payload, dict) else {}
        data = result.get("Data", {}) if isinstance(result, dict) else {}
        if not isinstance(data, dict) or str(data.get("VideoID") or "") != normalized_id:
            raise CollectorFailure(
                "VIDEO_PLAY_INFO_INVALID",
                "视频播放信息与请求的视频不匹配。",
            )
        play_infos = data.get("PlayInfoList")
        if not isinstance(play_infos, list):
            return []
        ranked: list[tuple[int, int, str]] = []
        for item in play_infos:
            if not isinstance(item, dict):
                continue
            try:
                bitrate = int(item.get("Bitrate") or 0)
            except (TypeError, ValueError):
                bitrate = 0
            # 同一清晰度优先使用备用 CDN。真实浏览器验证中，主 CDN 虽返回
            # 206，却未声明 Accept-Ranges，播放到首段缓冲末尾后无法续取；
            # 备用 CDN 返回等价媒体并支持连续字节范围请求。
            for priority, key in enumerate(("BackupPlayUrl", "MainPlayUrl")):
                value = item.get(key)
                if isinstance(value, str) and value.startswith(("http://", "https://")):
                    ranked.append((bitrate, -priority, value))
        if not ranked:
            return []
        ranked.sort(reverse=True)
        return [ranked[0][2]]

    def _fetch_comments(self, post_id: str, reply_count: int) -> list[dict[str, Any]]:
        if reply_count <= 0:
            return []
        comments: list[dict[str, Any]] = []
        cursor = 0
        while len(comments) < 10:
            payload, _ = self._json_api("comment_list", group_id=post_id, count=10, cursor=cursor)
            data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
            items = data.get("comment_data") if isinstance(data.get("comment_data"), list) else []
            for item in items:
                if not isinstance(item, dict):
                    continue
                profile = (
                    item.get("profile_info") if isinstance(item.get("profile_info"), dict) else {}
                )
                comments.append(
                    {
                        "platform_comment_id": str(
                            item.get("comment_id_str") or item.get("comment_id") or ""
                        )
                        or None,
                        "author": str(profile.get("name") or "").strip() or None,
                        "content": str(item.get("text") or "").strip() or None,
                        "published_at": _iso_time(item.get("create_time")),
                        "like_count": item.get("digg_count")
                        if isinstance(item.get("digg_count"), int)
                        else None,
                    }
                )
                if len(comments) >= 10:
                    break
            if len(comments) >= 10 or not data.get("has_more"):
                break
            next_cursor = data.get("cursor")
            if not isinstance(next_cursor, int) or next_cursor == cursor:
                break
            cursor = next_cursor
        return comments

    def collect_circle(
        self,
        circle_url: str,
        target_count: int,
        skip_post_ids: set[str] | None = None,
        on_progress: ProgressCallback | None = None,
        on_page_evidence: PageEvidenceCallback | None = None,
    ) -> dict[str, Any]:
        source = parse_circle_url(circle_url)
        records: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        seen: set[str] = set(skip_post_ids or set())
        page_number = 1
        page_count: int | None = None
        total_count: int | None = None
        exhausted = False
        candidate_position = 0
        max_page_number = max(1, math.ceil((len(seen) + target_count) / 30) + 5)
        while len(records) < target_count:
            expected = (
                None
                if total_count is None
                else min(30, max(0, total_count - (page_number - 1) * 30))
            )
            if on_page_evidence:
                loader = getattr(on_page_evidence, "load", None)
                captured = loader(page_number) if callable(loader) else None
                captured = captured or self.capture_circle_page(source.url, page_number)
                page = {
                    "rows": captured["rows"],
                    "total_count": None,
                    "page_count": None,
                }
            else:
                captured = None
                page = self._fetch_circle_page(source.url, page_number, expected)
            if page_number == 1:
                total_count = page["total_count"]
                page_count = (
                    math.ceil(total_count / 30) if total_count is not None else page["page_count"]
                )
            page_rows = page["rows"]
            if captured is not None:
                for row in page_rows:
                    row["source_position"] = candidate_position + int(
                        row.get("order_index", row.get("source_position", 0))
                    )
                captured["rows"] = page_rows
                if not captured.get("persisted"):
                    on_page_evidence(captured)
            if not page_rows:
                exhausted = True
                break
            candidates = [item for item in page_rows if item["post_id"] not in seen]
            if not candidates:
                # 认证续跑会从第一页重新发现候选；若本页内容已全部存在于检查点，
                # 这只表示本页已经处理完，不表示后续分页没有新内容。
                if page_count is not None and page_number < page_count:
                    page_number += 1
                    continue
                if captured is not None and page_number < max_page_number:
                    page_number += 1
                    continue
                exhausted = True
                break
            candidate_cursor = 0
            while candidate_cursor < len(candidates) and len(records) < target_count:
                batch_size = min(
                    self.concurrency,
                    len(candidates) - candidate_cursor,
                    target_count - len(records),
                )
                batch: list[tuple[dict[str, Any], int]] = []
                for candidate in candidates[candidate_cursor : candidate_cursor + batch_size]:
                    batch.append((candidate, candidate_position))
                    candidate_position += 1
                    seen.add(candidate["post_id"])
                candidate_cursor += batch_size

                def fetch_candidate(value: tuple[dict[str, Any], int]) -> tuple[Any, Any, int]:
                    candidate, source_index = value
                    try:
                        return self.fetch_post(candidate["url"]), None, source_index
                    except (AuthenticationRequired, CollectorFailure) as exc:
                        return None, exc, source_index

                with ThreadPoolExecutor(max_workers=len(batch)) as pool:
                    results = list(pool.map(fetch_candidate, batch))
                for (candidate, _source_index), (record, error, source_index) in zip(
                    batch, results, strict=True
                ):
                    if isinstance(error, AuthenticationRequired):
                        raise AuthenticationRequired(
                            error.message,
                            trigger_url=candidate["url"],
                            records=records,
                            failures=failures,
                        ) from error
                    if isinstance(error, CollectorFailure):
                        failure = {
                            "url": candidate["url"],
                            "code": error.code,
                            "message": error.message,
                            "source_index": source_index,
                        }
                        failures.append(failure)
                        if on_progress:
                            on_progress(None, failure)
                        continue
                    if record is None:
                        failure = {
                            "url": candidate["url"],
                            "code": "POST_NOT_FOUND",
                            "message": "帖子详情当前不可用。",
                            "source_index": source_index,
                        }
                        failures.append(failure)
                        if on_progress:
                            on_progress(None, failure)
                        continue
                    record["order_index"] = source_index
                    records.append(record)
                    if on_progress:
                        on_progress(record, None)
            if len(records) >= target_count:
                break
            if page_count is not None and page_number >= page_count:
                exhausted = True
                break
            if page_count is None and page_number >= max_page_number:
                exhausted = True
                break
            page_number += 1
        if len(records) >= target_count:
            stop_reason = "已经取得配置数量的有效帖子。"
        elif exhausted:
            stop_reason = "平台没有更多可用内容，按实际有效数量结束。"
        else:
            stop_reason = "候选帖子存在错误，未能取得配置数量的有效结果。"
        return {"records": records, "failures": failures, "stop_reason": stop_reason}

    def collect_urls(
        self, urls: list[str], on_progress: ProgressCallback | None = None
    ) -> dict[str, Any]:
        records: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        seen: set[str] = set()
        for source_index, url in enumerate(urls):
            try:
                post_id, normalized = normalize_post_url(url)
            except CollectorFailure as exc:
                failure = {
                    "url": url,
                    "code": exc.code,
                    "message": exc.message,
                    "source_index": source_index,
                }
                failures.append(failure)
                if on_progress:
                    on_progress(None, failure)
                continue
            if post_id in seen:
                continue
            seen.add(post_id)
            try:
                record = self.fetch_post(normalized)
            except AuthenticationRequired as exc:
                raise AuthenticationRequired(
                    exc.message,
                    trigger_url=normalized,
                    records=records,
                    failures=failures,
                ) from exc
            if record is None:
                failure = {
                    "url": normalized,
                    "code": "POST_NOT_FOUND",
                    "message": "帖子详情当前不可用。",
                    "source_index": source_index,
                }
                failures.append(failure)
                if on_progress:
                    on_progress(None, failure)
                continue
            record["order_index"] = source_index
            records.append(record)
            if on_progress:
                on_progress(record, None)
        return {
            "records": records,
            "failures": failures,
            "stop_reason": "已处理全部导入帖子链接。",
        }
