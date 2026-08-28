"""易车社区列表、帖子详情和一级评论适配器。"""

from __future__ import annotations

import json
import re
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from math import ceil
from typing import Any, Callable, Iterable
from urllib.parse import parse_qs, urljoin, urlsplit
from zoneinfo import ZoneInfo

from json_repair import repair_json
from lxml import html
from patchright.sync_api import Page, sync_playwright

from ..browser_runtime import browser_launch_args
from .base import AuthenticationRequired, CircleSource, CollectorFailure

BASE_URL = "https://baa.yiche.com"
ADAPTER_VERSION = "yiche-community-v1"
CIRCLE_RE = re.compile(
    r"^/(?P<id>[A-Za-z0-9_-]+)/?"
    r"(?:index-0-(?P<order>[01])-(?P<page>\d+)\.html)?/?$"
)
POST_RE = re.compile(r"^/(?P<circle>[A-Za-z0-9_-]+)/thread-(?P<id>\d+)\.html/?$")
WAF_MARKERS = ("TencentCaptcha", "TCaptcha.js", "/WafCaptcha", "__captcha")
PUA_RE = re.compile("[\ue000-\uf8ff]")
YICHE_TIMEZONE = ZoneInfo("Asia/Shanghai")
ProgressCallback = Callable[[dict[str, Any] | None, dict[str, Any] | None], None]


@dataclass(frozen=True)
class ApiEvent:
    """页面本次导航产生的业务响应及其脱敏身份。"""

    path: str
    status: int
    payload: Any
    content_id: str | None = None


@dataclass(frozen=True)
class CommentResult:
    """已验证身份和终止边界的一级评论结果。"""

    comments: list[dict[str, Any]]
    termination: str


def _request_content_id(url: str, post_data: str | None = None) -> str | None:
    """只从页面请求参数提取帖子身份，不保留完整动态请求。"""

    candidates = list(parse_qs(urlsplit(url).query).get("param", []))
    if post_data:
        body = parse_qs(post_data)
        candidates.extend(body.get("param", []))
        if not candidates:
            candidates.append(post_data)
    for raw in candidates:
        try:
            value = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(value, dict) and value.get("contentId") is not None:
            return str(value["contentId"])
    return None


def parse_circle_url(url: str) -> CircleSource:
    """规范化易车社区的最新回复、最新发布和分页入口。"""

    parsed = urlsplit(url.strip())
    if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() != "baa.yiche.com":
        raise CollectorFailure("CIRCLE_URL_INVALID", "圈子链接必须来自易车社区 baa.yiche.com。")
    match = CIRCLE_RE.match(parsed.path)
    if not match:
        raise CollectorFailure(
            "CIRCLE_URL_INVALID",
            "易车圈子链接必须是社区首页或 index-0-0/1-页码.html 列表入口。",
        )
    circle_id = match.group("id")
    if match.group("order") == "1":
        query = parse_qs(parsed.query)
        if query.get("tag", ["-1"])[0] != "-1":
            raise CollectorFailure(
                "CIRCLE_URL_INVALID",
                "易车最新发布入口只支持已验证的 tag=-1 全部动态列表。",
            )
        return CircleSource(
            circle_id,
            f"{BASE_URL}/{circle_id}/index-0-1-1.html?tag=-1",
            "latest_publish",
        )
    return CircleSource(
        circle_id,
        f"{BASE_URL}/{circle_id}/index-0-0-1.html",
        "latest_reply",
    )


def normalize_circle_url(url: str) -> tuple[str, str]:
    """返回易车圈子稳定身份和规范 URL。"""

    source = parse_circle_url(url)
    return source.external_id, source.url


def normalize_post_url(url: str) -> tuple[str, str]:
    """规范化易车社区帖子详情链接。"""

    parsed = urlsplit(url.strip())
    if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() != "baa.yiche.com":
        raise CollectorFailure("POST_URL_INVALID", "帖子链接必须来自易车社区 baa.yiche.com。")
    match = POST_RE.match(parsed.path)
    if not match:
        raise CollectorFailure(
            "POST_URL_INVALID",
            "易车帖子链接必须是圈子下的 thread-数字.html 详情页。",
        )
    post_id = match.group("id")
    return post_id, f"{BASE_URL}/{match.group('circle')}/thread-{post_id}.html"


def _post_identity(url: str) -> tuple[str, str, str]:
    """返回帖子圈子短名、帖子ID和规范URL。"""

    post_id, normalized = normalize_post_url(url)
    match = POST_RE.match(urlsplit(normalized).path)
    assert match is not None
    return match.group("circle"), post_id, normalized


def is_waf_captcha(content: str | bytes) -> bool:
    """识别易车公开页面返回的腾讯验证码控制文档。"""

    text = content.decode("utf-8", errors="ignore") if isinstance(content, bytes) else content
    return sum(marker in text for marker in WAF_MARKERS) >= 2


def require_content_page(content: str | bytes, *, url: str) -> None:
    """控制页不能作为列表、详情或空结果进入有效结果分母。"""

    if is_waf_captcha(content):
        raise AuthenticationRequired(
            "易车页面触发腾讯验证码，请在服务器浏览器完成验证后继续。",
            trigger_url=url,
        )
    if not content or not content.strip():
        raise CollectorFailure("EMPTY_RESPONSE", "易车页面返回空响应。")


def _unique_urls(values: Iterable[object], *, base_url: str = BASE_URL) -> list[str]:
    output: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            continue
        normalized = urljoin(base_url, value.strip())
        if normalized.startswith(("http://", "https://")) and normalized not in output:
            output.append(normalized)
    return output


def _parse_time(value: object) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=YICHE_TIMEZONE)
    except ValueError:
        return None


def _integer(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None


class YicheCollector:
    """使用公开网页同款 API 发现来源，并以详情页确认帖子身份与正文。"""

    code = "yiche"
    display_name = "易车"
    adapter_version = ADAPTER_VERSION
    supports_page_evidence = False
    supports_live_video_resolution = False

    def __init__(
        self,
        storage_state: dict[str, Any] | None,
        concurrency: int = 1,
        timeout_seconds: int = 30,
        browser_headless: bool = False,
    ):
        self.storage_state = storage_state
        self.concurrency = max(1, concurrency)
        self.timeout_seconds = timeout_seconds
        self.browser_headless = browser_headless

    @contextmanager
    def _browser_page(self) -> Iterable[Page]:
        """一个采集动作复用一个真实浏览器页，由页面生成动态签名请求。"""

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=self.browser_headless,
                args=browser_launch_args(),
            )
            context = browser.new_context(
                storage_state=self.storage_state,
                locale="zh-CN",
                timezone_id="Asia/Shanghai",
            )
            page = context.new_page()
            try:
                yield page
            finally:
                context.close()
                browser.close()

    def _navigate(self, page: Page, url: str) -> tuple[str, list[ApiEvent], str]:
        """加载官方页面并冻结本次页面实际产生的 API 响应。"""

        responses: list[Any] = []

        def handle_response(response: Any) -> None:
            """使用可附加属性的 Python 函数接收 Patchright 页面事件。"""

            responses.append(response)

        handler = handle_response
        page.on("response", handler)
        try:
            response = page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=self.timeout_seconds * 1000,
            )
            page.wait_for_timeout(1500)
            status = response.status if response else None
            content = page.content()
            # 腾讯 WAF 实测可能以 203 返回；控制文档身份必须先于通用 HTTP 分类。
            if is_waf_captcha(content):
                require_content_page(content, url=url)
            final_url = page.url
            # goto 可能只返回挑战阶段的 203；仅以最终 URL 的后续主文档响应覆盖它。
            for item in responses:
                request = getattr(item, "request", None)
                if (
                    getattr(request, "resource_type", None) == "document"
                    and urlsplit(str(getattr(item, "url", "")))._replace(fragment="")
                    == urlsplit(final_url)._replace(fragment="")
                ):
                    status = item.status
            if status == 429:
                raise CollectorFailure("RATE_LIMITED", "易车页面返回限流状态，请稍后重试。")
            if status in {401, 403}:
                raise AuthenticationRequired("易车访问会话需要更新。", trigger_url=url)
            if status is None:
                raise CollectorFailure("HTTP_RESPONSE_MISSING", "易车页面没有返回主文档响应。")
            if status != 200:
                raise CollectorFailure("HTTP_ERROR", f"易车页面返回 HTTP {status}。")
            require_content_page(content, url=url)
            events: list[ApiEvent] = []
            for item in responses:
                path = urlsplit(item.url).path
                if "/web_api/" not in path:
                    continue
                payload: Any = None
                try:
                    payload = item.json()
                except Exception:
                    pass
                events.append(
                    ApiEvent(
                        path=path,
                        status=item.status,
                        payload=payload,
                        content_id=_request_content_id(
                            item.request.url, item.request.post_data
                        ),
                    )
                )
            return content, events, final_url
        finally:
            page.remove_listener("response", handler)

    @staticmethod
    def _api_payload(
        events: list[ApiEvent],
        path_suffix: str,
        *,
        required: bool = True,
        expected_content_id: str | None = None,
    ) -> dict[str, Any] | None:
        """读取浏览器真实响应并保留平台业务错误码。"""

        matched = [item for item in events if item.path.lower().endswith(path_suffix.lower())]
        if not matched:
            if required:
                raise CollectorFailure("API_RESPONSE_MISSING", "易车页面未产生预期业务响应。")
            return None
        event = matched[-1]
        if event.status == 429:
            raise CollectorFailure("RATE_LIMITED", "易车接口返回限流状态，请稍后重试。")
        if event.status != 200:
            raise CollectorFailure("HTTP_ERROR", f"易车接口返回 HTTP {event.status}。")
        payload = event.payload
        if not isinstance(payload, dict):
            raise CollectorFailure("RESPONSE_INVALID", "易车接口返回了非 JSON 内容。")
        if str(payload.get("status")) != "1":
            code = str(payload.get("ercd") or payload.get("status") or "unknown")
            message = str(payload.get("message") or "易车接口返回失败状态。")
            if code == "11036":
                failure_code = "YICHE_PUBLIC_PARAMS_MISSING"
            elif path_suffix.lower().endswith("/comment/top_comment_list") and code == "400":
                failure_code = "YICHE_COMMENT_IDENTITY_MISSING"
            else:
                failure_code = "PLATFORM_RESPONSE_ERROR"
            raise CollectorFailure(failure_code, f"{message}（业务码 {code}）")
        if expected_content_id is not None and event.content_id != expected_content_id:
            raise CollectorFailure(
                "COMMENTS_IDENTITY_MISMATCH",
                "易车一级评论请求未绑定当前帖子身份。",
            )
        return payload

    def _list_page(self, page: Page, source: CircleSource, page_number: int) -> dict[str, Any]:
        suffix = f"index-0-{1 if source.list_order == 'latest_publish' else 0}-{page_number}.html"
        url = f"{BASE_URL}/{source.external_id}/{suffix}"
        if source.list_order == "latest_publish":
            url += "?tag=-1"
        content, events, _final_url = self._navigate(page, url)
        payload = self._api_payload(events, "/post/getlist")
        assert payload is not None
        data = payload.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("list"), list):
            raise CollectorFailure("LIST_RESPONSE_INVALID", "易车帖子列表响应结构无效。")
        document = html.fromstring(content)
        dom_ids = [
            str(node.get("data-id") or "")
            for node in document.cssselect(
                '.power-list .list-theme .list-web .col-panel > a.col-row.bankuai[data-dtype="post"][data-id]'
            )
        ]
        api_ids = [str(item.get("id") or "") for item in data["list"] if isinstance(item, dict)]
        if dom_ids and dom_ids != api_ids:
            raise CollectorFailure("LIST_IDENTITY_MISMATCH", "易车列表 DOM 与业务响应身份不一致。")
        forum_payload = self._api_payload(events, "/forum/get", required=False)
        forum_id_payload = self._api_payload(events, "/forum/getid", required=False)
        forum = forum_payload.get("data") if forum_payload else None
        return {
            **data,
            "forum": forum if isinstance(forum, dict) else None,
            "forum_id_lookup": forum_id_payload.get("data") if forum_id_payload else None,
        }

    def validate_circle(self, circle_url: str) -> dict[str, Any]:
        source = parse_circle_url(circle_url)
        with self._browser_page() as browser_page:
            page = self._list_page(browser_page, source, 1)
            rows = page.get("list") or []
            if not rows:
                raise CollectorFailure(
                    "CIRCLE_VALIDATION_FAILED", "易车社区没有返回可验证的帖子。"
                )
            first = rows[0] if isinstance(rows[0], dict) else {}
            forum_id = _integer(first.get("forumId"))
            forum_name = str(first.get("forumName") or "").strip()
            seo_name = str(first.get("forumApp") or "").strip()
            forum = page.get("forum") or {}
            if not forum_id or _integer(page.get("forum_id_lookup")) != forum_id:
                raise CollectorFailure(
                    "CIRCLE_IDENTITY_MISMATCH", "易车社区与列表帖子身份不一致。"
                )
            if (
                not forum_name
                or not seo_name
                or seo_name.lower() != source.external_id.lower()
                or _integer(forum.get("id")) != forum_id
                or str(forum.get("forumApp") or "").strip().lower() != seo_name.lower()
                or str(forum.get("name") or "").strip() != forum_name
            ):
                raise CollectorFailure(
                    "CIRCLE_IDENTITY_MISMATCH", "易车社区短名与稳定身份不一致。"
                )
            first_url = f"{BASE_URL}/{source.external_id}/thread-{first.get('id')}.html"
            self._fetch_post(browser_page, first_url, list_row=first)
        return {
            "external_id": source.external_id,
            "forum_id": forum_id,
            "seo_name": seo_name,
            "forum_name": forum_name,
            "name": forum_name,
            "url": source.url,
            "sort": source.list_order,
            "adapter_version": self.adapter_version,
        }

    def validate_auth(self, probe_url: str) -> dict[str, Any]:
        """有已配置圈子时执行真实样本门禁，否则只确认根页离开 WAF。"""

        if urlsplit(probe_url).path.strip("/"):
            return self.validate_circle(probe_url)

        with self._browser_page() as browser_page:
            self._navigate(browser_page, probe_url)
        return {"platform": self.code, "access_session_available": True}

    @staticmethod
    def _detail_payload(content: str, post_url: str) -> dict[str, Any]:
        document = html.fromstring(content)
        root = document.cssselect(".club-detail.postcontbox .postcont-list.post-fist")
        expected_circle, expected_id, normalized_url = _post_identity(post_url)
        if not root or str(root[0].get("data-id") or "") != expected_id:
            raise CollectorFailure("POST_IDENTITY_MISMATCH", "易车详情页身份与请求帖子不一致。")
        structured: dict[str, Any] | None = None
        for script in document.xpath('//script[@type="application/ld+json"]'):
            try:
                candidate = json.loads(repair_json(script.text or ""))
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
            if isinstance(candidate, dict) and candidate.get("@type") == "DiscussionForumPosting":
                structured = candidate
                break
        if not structured:
            raise CollectorFailure("POST_DETAIL_INVALID", "易车详情页缺少帖子结构化正文。")
        identity_url = str(
            structured.get("mainEntityOfPage") or structured.get("url") or ""
        ).strip()
        try:
            identity_circle, identity_id, _ = _post_identity(identity_url)
        except CollectorFailure as exc:
            raise CollectorFailure("POST_IDENTITY_MISMATCH", "易车结构化详情身份无效。") from exc
        if identity_id != expected_id or identity_circle.lower() != expected_circle.lower():
            raise CollectorFailure("POST_IDENTITY_MISMATCH", "易车结构化详情身份与 URL 不一致。")
        body = str(structured.get("text") or "").strip()
        if PUA_RE.search(body):
            raise CollectorFailure("POST_CONTENT_OBFUSCATED", "易车详情正文仍含未还原的私有区字符。")
        author = structured.get("author") if isinstance(structured.get("author"), dict) else {}
        image_values = structured.get("image")
        if not isinstance(image_values, list):
            image_values = [image_values] if image_values else []
        image_urls = _unique_urls(image_values, base_url=normalized_url)
        if not image_urls:
            image_urls = _unique_urls(
                [
                    node.get("data-original") or node.get("data-webp") or node.get("src")
                    for node in root[0].cssselect(".post-content .post-wrap img")
                ],
                base_url=normalized_url,
            )
        video_urls = _unique_urls(
            [
                node.get("src")
                for node in root[0].cssselect(
                    '.post-wrap .video-wrapper video.vjs-tech source[type="video/mp4"]'
                )
            ],
            base_url=normalized_url,
        )
        reply_text = root[0].xpath('string(.//*[@id="huiNumber"])').strip()
        like_count = None
        for item in structured.get("interactionStatistic") or []:
            if isinstance(item, dict) and str(item.get("interactionType") or "").endswith(
                "LikeAction"
            ):
                like_count = _integer(item.get("userInteractionCount"))
                break
        return {
            "platform_post_id": expected_id,
            "url": normalized_url,
            "title": str(structured.get("headline") or "").strip() or None,
            "author": str(author.get("name") or root[0].get("data-name") or "").strip()
            or None,
            "published_at": _parse_time(structured.get("datePublished")),
            "content": body or None,
            "image_urls": image_urls,
            "video_urls": video_urls,
            "reply_count": _integer(reply_text),
            "like_count": like_count,
            "section": "dynamic",
            "visibility": "unknown",
        }

    def _parse_comments(
        self,
        content: str,
        events: list[ApiEvent],
        reply_count: int | None,
        expected_content_id: str,
    ) -> CommentResult:
        """解析页面首批一级评论；当前页面每批20条，系统最多保留10条。"""

        payload = self._api_payload(
            events,
            "/comment/top_comment_list",
            required=False,
            expected_content_id=expected_content_id,
        )
        comments: list[dict[str, Any]] = []
        if payload:
            data = payload.get("data")
            if not isinstance(data, dict) or not isinstance(data.get("list"), list):
                raise CollectorFailure("COMMENTS_RESPONSE_INVALID", "易车一级评论响应结构无效。")
            for item in data["list"][:10]:
                if not isinstance(item, dict):
                    continue
                content_data = (
                    item.get("contentData") if isinstance(item.get("contentData"), dict) else {}
                )
                comments.append(
                    {
                        "platform_comment_id": str(item.get("id") or item.get("uuid") or "")
                        or None,
                        "author": str(item.get("showName") or "").strip() or None,
                        "content": str(
                            content_data.get("contentText") or item.get("content") or ""
                        ).strip()
                        or None,
                        "published_at": _parse_time(item.get("createTime")),
                        "like_count": _integer(item.get("likeCount")),
                    }
                )
            if len(comments) >= 10:
                return CommentResult(comments, "cap_10")
            rows = data["list"]
            if not rows:
                return CommentResult(comments, "empty_list")
            have_next = data.get("haveNextPage")
            current_page = _integer(data.get("currentPage"))
            page_size = _integer(data.get("pageSize"))
            total = _integer(data.get("total"))
            count_proves_terminal = bool(
                current_page
                and page_size
                and page_size > 0
                and total is not None
                and total >= 0
                and current_page >= max(1, ceil(total / page_size))
            )
            if have_next is True and count_proves_terminal:
                raise CollectorFailure(
                    "COMMENTS_TERMINATION_CONFLICT",
                    "易车一级评论的下一页标记与数量边界冲突。",
                )
            if have_next is False or (have_next is None and count_proves_terminal):
                return CommentResult(
                    comments,
                    "have_next_false" if have_next is False else "count_boundary",
                )
            if have_next is True:
                raise CollectorFailure(
                    "COMMENTS_PAGINATION_UNVERIFIED",
                    "易车当前评论页不足10条但仍声明后续页，未验证的翻页结果不计入有效帖子。",
                )
            raise CollectorFailure(
                "COMMENTS_TERMINATION_UNPROVEN",
                "易车一级评论响应没有可验证的分页终止证明。",
            )
        del content, reply_count
        raise CollectorFailure(
            "COMMENTS_RESPONSE_MISSING",
            "易车详情未捕获到带帖子身份和终止证明的一级评论业务响应。",
        )

    def _fetch_post(
        self, page: Page, post_url: str, *, list_row: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        expected_circle, expected_id, normalized_url = _post_identity(post_url)
        content, events, final_url = self._navigate(page, normalized_url)
        final_circle, final_id, _ = _post_identity(final_url)
        if final_id != expected_id or final_circle.lower() != expected_circle.lower():
            raise CollectorFailure(
                "POST_IDENTITY_MISMATCH", "易车详情最终导航地址与请求帖子不一致。"
            )
        record = self._detail_payload(content, normalized_url)
        if record["platform_post_id"] != expected_id:
            raise CollectorFailure("POST_IDENTITY_MISMATCH", "易车详情结果与请求帖子不一致。")
        row = list_row or {}
        row_id = str(row.get("id") or "")
        row_circle = str(row.get("forumApp") or "").strip()
        if row_id and (
            row_id != expected_id or row_circle.lower() != expected_circle.lower()
        ):
            raise CollectorFailure("POST_IDENTITY_MISMATCH", "易车列表与详情帖子身份不一致。")
        if record["reply_count"] is None:
            record["reply_count"] = _integer(row.get("repliesNum"))
        comment_result = self._parse_comments(
            content, events, record["reply_count"], expected_id
        )
        record["comments"] = comment_result.comments
        record["raw_status"] = {
            "forum_id": _integer(row.get("forumId")),
            "forum_name": str(row.get("forumName") or "").strip() or None,
            "forum_app": str(row.get("forumApp") or "").strip() or None,
            "post_type": _integer(row.get("postType")),
            "is_banned": row.get("isBanned") if isinstance(row.get("isBanned"), bool) else None,
            "is_all_banned": row.get("isAllBanned")
            if isinstance(row.get("isAllBanned"), bool)
            else None,
            "is_closed": row.get("isClosed") if isinstance(row.get("isClosed"), bool) else None,
            "lock_status": _integer(row.get("lockStatus")),
            "verify_status": _integer(row.get("verifyStatus")),
            "source": _integer(row.get("source")),
            "document_http_status": 200,
            "document_classification": "content",
            "detail_identity_verified": True,
            "list_identity_verified": bool(row_id),
            "comment_api_business_status": "1",
            "comment_api_status": "success",
            "comment_identity_verified": True,
            "comment_termination": comment_result.termination,
        }
        if not record["content"] and not record["image_urls"] and not record["video_urls"]:
            raise CollectorFailure("POST_CONTENT_EMPTY", "易车详情没有返回正文或媒体。")
        record["visibility"] = "visible"
        return record

    def fetch_post(
        self, post_url: str, *, list_row: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """用一个短期真实浏览器上下文采集单个详情。"""

        with self._browser_page() as page:
            return self._fetch_post(page, post_url, list_row=list_row)

    def collect_circle(
        self,
        circle_url: str,
        target_count: int,
        *,
        skip_post_ids: set[str] | None = None,
        on_progress: ProgressCallback | None = None,
        on_page_evidence: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        del on_page_evidence
        source = parse_circle_url(circle_url)
        records: list[dict[str, Any]] = []
        failures: list[dict[str, str]] = []
        seen = set(skip_post_ids or set())
        candidate_ids: set[str] = set()
        page_number = 1
        frozen_total: int | None = None
        source_index = 0
        stop_reason = "易车列表已经没有更多帖子。"
        with self._browser_page() as browser_page:
            while len(records) < target_count:
                page = self._list_page(browser_page, source, page_number)
                rows = page.get("list") or []
                if not rows:
                    break
                current_total = _integer(page.get("total"))
                if current_total is None or current_total < 0:
                    raise CollectorFailure("LIST_TOTAL_INVALID", "易车列表没有返回有效总量。")
                if frozen_total is None:
                    frozen_total = current_total
                elif current_total != frozen_total:
                    raise CollectorFailure(
                        "LIST_TOTAL_CHANGED",
                        f"易车列表分页总量从 {frozen_total} 变为 {current_total}，本次快照已停止。",
                    )
                new_candidates = 0
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    post_id = str(row.get("id") or "").strip()
                    if not post_id or post_id in candidate_ids:
                        continue
                    candidate_ids.add(post_id)
                    new_candidates += 1
                    index = source_index
                    source_index += 1
                    if post_id in seen:
                        continue
                    url = f"{BASE_URL}/{source.external_id}/thread-{post_id}.html"
                    try:
                        record = self._fetch_post(browser_page, url, list_row=row)
                        record["order_index"] = index
                        records.append(record)
                        seen.add(post_id)
                        if on_progress:
                            on_progress(record, None)
                    except AuthenticationRequired as exc:
                        exc.records = records
                        exc.failures = failures
                        raise
                    except CollectorFailure as exc:
                        failure = {
                            "url": url,
                            "code": exc.code,
                            "message": exc.message,
                            "source_index": str(index),
                        }
                        failures.append(failure)
                        if on_progress:
                            on_progress(None, failure)
                    if len(records) >= target_count:
                        stop_reason = "已经取得配置数量的有效帖子。"
                        break
                if len(records) >= target_count:
                    break
                if page_number * 50 >= frozen_total:
                    break
                if new_candidates == 0:
                    stop_reason = "易车列表分页没有返回新的帖子身份。"
                    break
                page_number += 1
        return {"records": records, "failures": failures, "stop_reason": stop_reason}

    def collect_urls(
        self, urls: list[str], *, on_progress: ProgressCallback | None = None
    ) -> dict[str, Any]:
        records: list[dict[str, Any]] = []
        failures: list[dict[str, str]] = []
        seen: set[str] = set()
        with self._browser_page() as browser_page:
            for source_index, raw_url in enumerate(urls):
                try:
                    post_id, normalized_url = normalize_post_url(raw_url)
                except CollectorFailure as exc:
                    failure = {
                        "url": raw_url,
                        "code": exc.code,
                        "message": exc.message,
                        "source_index": str(source_index),
                    }
                    failures.append(failure)
                    if on_progress:
                        on_progress(None, failure)
                    continue
                if post_id in seen:
                    continue
                seen.add(post_id)
                try:
                    record = self._fetch_post(browser_page, normalized_url)
                    record["order_index"] = source_index
                    records.append(record)
                    if on_progress:
                        on_progress(record, None)
                except AuthenticationRequired as exc:
                    exc.records = records
                    exc.failures = failures
                    raise
                except CollectorFailure as exc:
                    failure = {
                        "url": normalized_url,
                        "code": exc.code,
                        "message": exc.message,
                        "source_index": str(source_index),
                    }
                    failures.append(failure)
                    if on_progress:
                        on_progress(None, failure)
        return {
            "records": records,
            "failures": failures,
            "stop_reason": "URL 清单处理完成。",
        }
