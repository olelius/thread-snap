"""汽车之家论坛来源、帖子详情与前十条一级回复适配器。"""

from __future__ import annotations

import html as html_module
import json
import math
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Iterable
from urllib.parse import parse_qs, unquote_plus, urljoin
from zoneinfo import ZoneInfo

from curl_cffi import requests
from curl_cffi.requests import Cookies
from lxml import html

from .base import (
    AuthenticationRequired,
    CircleSource,
    CollectorFailure,
    PageEvidenceCallback,
    ProgressCallback,
)

ADAPTER_VERSION = "autohome-club-v1"
BASE_URL = "https://club.autohome.com.cn"
LIST_API_URL = "https://club-open-api.autohome.com.cn/api/pc/bbs/index/getClubTopicList"
PAGE_SIZE = 50
FORUM_RE = re.compile(
    r"^https?://club\.autohome\.com\.cn/bbs/forum-(?P<type>[a-zA-Z])-(?P<id>\d+)-"
    r"(?P<page>\d+)\.html/?(?:\?(?P<query>[^#]*))?(?:#.*)?$"
)
POST_RE = re.compile(
    r"^https?://club\.autohome\.com\.cn/bbs/thread/(?P<hash>[A-Za-z0-9_-]+)/"
    r"(?P<id>\d+)-(?P<page>\d+)\.html/?(?:[?#].*)?$"
)
TOPIC_BLOCK_RE = re.compile(
    r"window\[['\"]__TOPICINFO__['\"]\]\s*=\s*\{(?P<body>.*?)\};",
    re.DOTALL,
)
BBS_INFO_RE = re.compile(
    r"window\[['\"]__BBSINFO__['\"]\]\s*=\s*(?P<value>\{[^\r\n]*\})",
)
VIDEO_INFO_RE = re.compile(
    r"window(?:\[['\"]__VIDEOINFO__['\"]\]|\.__VIDEOINFO__)\s*=\s*"
    r"(?P<value>\{.*?\})\s*;",
    re.DOTALL,
)
CONTROL_MARKERS = {
    "captcha": ("验证码", "captcha"),
    "challenge": ("安全验证", "访问验证", "滑块", "challenge"),
    "rate_limited": ("请求频繁", "访问过于频繁", "rate limit", "too many requests"),
    "login": ("passport.autohome.com.cn", "登录汽车之家", "请先登录"),
}


def parse_circle_url(url: str) -> CircleSource:
    """解析论坛 URL，并只接受已证明的最后回复或最新发布顺序。"""

    match = FORUM_RE.match(url.strip())
    if not match:
        raise CollectorFailure(
            "CIRCLE_URL_INVALID",
            "汽车之家来源链接格式无效，必须是 club.autohome.com.cn 的论坛链接。",
        )
    bbs_type = match.group("type").lower()
    bbs_id = match.group("id")
    if int(bbs_id) <= 0:
        raise CollectorFailure("CIRCLE_URL_INVALID", "汽车之家论坛 ID 必须是正整数。")
    query = parse_qs(match.group("query") or "", keep_blank_values=True)
    sort = (query.get("sort") or [""])[0].strip().lower()
    if sort in {"", "post"}:
        list_order = "latest_reply"
        canonical_sort = "post"
    elif sort == "topic":
        list_order = "latest_publish"
        canonical_sort = "topic"
    else:
        raise CollectorFailure(
            "CIRCLE_URL_INVALID", "汽车之家论坛链接包含未验证的列表顺序。"
        )
    canonical = f"{BASE_URL}/bbs/forum-{bbs_type}-{bbs_id}-1.html?sort={canonical_sort}"
    return CircleSource(
        external_id=bbs_id,
        url=canonical,
        list_order=list_order,
        raw_status={"bbs_type": bbs_type, "bbs_id": int(bbs_id)},
    )


def normalize_circle_url(url: str) -> tuple[str, str]:
    """返回平台稳定来源 ID 与规范论坛 URL。"""

    source = parse_circle_url(url)
    return source.external_id, source.url


def normalize_post_url(url: str) -> tuple[str, str]:
    """规范汽车之家 hash-thread URL，并把详情页码固定为第一页。"""

    match = POST_RE.match(url.strip())
    if not match or int(match.group("id") or 0) <= 0:
        raise CollectorFailure(
            "POST_URL_INVALID",
            "帖子链接格式无效，必须是汽车之家论坛 thread 详情链接。",
        )
    post_id = match.group("id")
    canonical = f"{BASE_URL}/bbs/thread/{match.group('hash')}/{post_id}-1.html"
    return post_id, canonical


def _cookies_from_state(state: dict[str, Any] | None) -> Cookies:
    """只导入汽车之家域且仍有效的浏览器 Cookie。"""

    jar = Cookies()
    now = time.time()
    for item in (state or {}).get("cookies", []):
        if not isinstance(item, dict):
            continue
        domain = str(item.get("domain") or "")
        if "autohome.com.cn" not in domain:
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


def _unique_urls(values: Iterable[object]) -> list[str]:
    """保序去重并补全协议相对媒体 URL。"""

    output: list[str] = []
    for raw in values:
        value = str(raw or "").strip()
        if value.startswith("//"):
            value = f"https:{value}"
        elif value.startswith("http://"):
            value = f"https://{value.removeprefix('http://')}"
        elif value and not value.startswith("https://"):
            value = urljoin(BASE_URL, value)
        if value.startswith("https://") and value not in output:
            output.append(value)
    return output


def _parse_platform_time(value: object) -> datetime | None:
    """把汽车之家北京时间文本转为 UTC 时间。"""

    text = str(value or "").strip()
    if not text:
        return None
    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
        try:
            local = datetime.strptime(text, pattern).replace(tzinfo=ZoneInfo("Asia/Shanghai"))
            return local.astimezone(timezone.utc)
        except ValueError:
            continue
    return None


def _integer(value: object) -> int | None:
    """只接受可无损解释为整数的值。"""

    if isinstance(value, bool):
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _class_tokens(name: str) -> str:
    return f" contains(concat(' ', normalize-space(@class), ' '), ' {name} ') "


def _js_int(block: str, key: str) -> int | None:
    match = re.search(rf"\b{re.escape(key)}\s*:\s*(-?\d+)", block)
    return int(match.group(1)) if match else None


def _js_string(block: str, key: str) -> str | None:
    match = re.search(rf"\b{re.escape(key)}\s*:\s*'((?:\\.|[^'])*)'", block)
    if not match:
        return None
    value = match.group(1).replace("\\'", "'").replace("\\\\", "\\")
    return html_module.unescape(value).strip() or None


class AutohomeCollector:
    """匿名优先的汽车之家论坛采集器；当前安全并发在正式验收前固定为一。"""

    code = "autohome"
    display_name = "汽车之家"
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
        self.cookies = _cookies_from_state(storage_state)
        self.concurrency = max(1, concurrency)
        self.timeout_seconds = timeout_seconds
        self.browser_headless = browser_headless
        self.semaphore = threading.BoundedSemaphore(self.concurrency)
        self._thread_local = threading.local()

    def _http_session(self) -> requests.Session:
        """为每个采集线程建立独立 Session，避免共享可变连接状态。"""

        session = getattr(self._thread_local, "http", None)
        if session is None:
            session = requests.Session(impersonate="chrome")
            session.cookies.update(self.cookies)
            self._thread_local.http = session
        return session

    def _get(self, url: str, **params: object) -> requests.Response:
        """执行有界 GET；平台控制分类由响应检查统一完成。"""

        last_error: Exception | None = None
        for attempt in range(3):
            try:
                with self.semaphore:
                    response = self._http_session().get(
                        url,
                        params=params or None,
                        timeout=self.timeout_seconds,
                        allow_redirects=True,
                    )
                if response.status_code >= 500 and attempt < 2:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                self._detect_control(response)
                return response
            except (AuthenticationRequired, CollectorFailure):
                raise
            except Exception as exc:  # curl_cffi 传输异常类型较多，统一有界重试。
                last_error = exc
                if attempt < 2:
                    time.sleep(0.5 * (attempt + 1))
        raise CollectorFailure("PLATFORM_NETWORK_ERROR", f"访问汽车之家失败：{last_error}")

    @staticmethod
    def _detect_control(response: requests.Response) -> None:
        """保守区分登录、验证码、挑战、限流和异常空响应。"""

        content = bytes(response.content or b"")
        final_url = str(getattr(response, "url", "") or "")
        text = content[:300_000].decode("utf-8", errors="ignore")
        try:
            document = html.fromstring(content)
            visible = " ".join(document.xpath("//title/text() | //body//text()[not(ancestor::script)]"))
        except (TypeError, ValueError):
            visible = text[:10_000]
        combined = f"{final_url}\n{visible}".lower()
        if int(response.status_code) == 429 or any(
            marker in combined for marker in CONTROL_MARKERS["rate_limited"]
        ):
            raise CollectorFailure("PLATFORM_RATE_LIMITED", "汽车之家当前限制了请求频率。")
        if any(marker in combined for marker in CONTROL_MARKERS["captcha"]):
            raise CollectorFailure("PLATFORM_CAPTCHA_REQUIRED", "汽车之家当前要求完成验证码。")
        if "safety.autohome.com.cn/userverify" in combined:
            raise CollectorFailure("PLATFORM_CHALLENGE", "汽车之家当前返回了访问验证页面。")
        if any(marker in combined for marker in CONTROL_MARKERS["challenge"]):
            raise CollectorFailure("PLATFORM_CHALLENGE", "汽车之家当前返回了访问验证页面。")
        if any(marker in combined for marker in CONTROL_MARKERS["login"]):
            raise AuthenticationRequired("汽车之家当前要求重新完成平台认证。", trigger_url=final_url)
        if not content:
            raise CollectorFailure("PLATFORM_RESPONSE_EMPTY", "汽车之家返回了异常空响应。")

    def _list_page(self, source: CircleSource, page_number: int) -> dict[str, Any]:
        """读取一个有序列表 API 页面并校验来源身份与响应结构。"""

        order_type = 2 if source.list_order == "latest_publish" else 1
        response = self._get(
            LIST_API_URL,
            _appid="club",
            scenes=1,
            page_num=page_number,
            page_size=PAGE_SIZE,
            club_bbs_type=source.raw_status.get("bbs_type", "c"),
            club_bbs_id=source.external_id,
            club_order_type=order_type,
        )
        if int(response.status_code) == 404:
            raise CollectorFailure("CIRCLE_NOT_FOUND", "汽车之家论坛来源当前不存在。")
        try:
            payload = json.loads(response.content)
        except (TypeError, json.JSONDecodeError) as exc:
            raise CollectorFailure(
                "PLATFORM_RESPONSE_INVALID", "汽车之家列表接口返回了无法识别的数据。"
            ) from exc
        if not isinstance(payload, dict):
            raise CollectorFailure("PLATFORM_RESPONSE_INVALID", "汽车之家列表接口返回结构无效。")
        message = str(payload.get("message") or "")
        self._detect_payload_control(message)
        result = payload.get("result")
        if payload.get("returncode") != 0 or not isinstance(result, dict):
            raise CollectorFailure("PLATFORM_RESPONSE_INVALID", "汽车之家列表接口返回结构无效。")
        items = result.get("items")
        if not isinstance(items, list):
            raise CollectorFailure("PLATFORM_RESPONSE_INVALID", "汽车之家列表缺少帖子数组。")
        return {
            "items": items,
            "total": _integer(result.get("total")),
            "series_id": result.get("seriesid"),
        }

    @staticmethod
    def _detect_payload_control(message: str) -> None:
        normalized = message.lower()
        if any(marker in normalized for marker in CONTROL_MARKERS["login"]):
            raise AuthenticationRequired("汽车之家当前要求重新完成平台认证。")
        if any(marker in normalized for marker in CONTROL_MARKERS["captcha"]):
            raise CollectorFailure("PLATFORM_CAPTCHA_REQUIRED", "汽车之家当前要求完成验证码。")
        if any(marker in normalized for marker in CONTROL_MARKERS["challenge"]):
            raise CollectorFailure("PLATFORM_CHALLENGE", "汽车之家当前返回了访问验证。")
        if any(marker in normalized for marker in CONTROL_MARKERS["rate_limited"]):
            raise CollectorFailure("PLATFORM_RATE_LIMITED", "汽车之家当前限制了请求频率。")

    @staticmethod
    def _candidate(source: CircleSource, item: object, source_index: int) -> dict[str, Any]:
        """把列表项收敛为稳定帖子候选，不信任跨来源或错帖数据。"""

        if not isinstance(item, dict):
            raise CollectorFailure("PLATFORM_RESPONSE_INVALID", "汽车之家列表包含无效帖子项。")
        bbs_id = _integer(item.get("club_bbs_id"))
        bbs_type = str(item.get("club_bbs_type") or "").lower()
        if bbs_id != int(source.external_id) or bbs_type != source.raw_status.get("bbs_type"):
            raise CollectorFailure("WRONG_POST", "汽车之家列表帖子不属于当前论坛来源。")
        post_id = _integer(item.get("biz_id"))
        if not post_id or post_id <= 0:
            raise CollectorFailure("PLATFORM_RESPONSE_INVALID", "汽车之家列表帖子缺少稳定 ID。")
        normalized_id, url = normalize_post_url(str(item.get("pc_url") or ""))
        if normalized_id != str(post_id):
            raise CollectorFailure("POST_ID_MISMATCH", "汽车之家列表帖子 ID 与链接不一致。")
        return {
            "post_id": str(post_id),
            "url": url,
            "order_index": source_index,
            "bbs_id": bbs_id,
            "bbs_type": bbs_type,
            "title_hint": str(item.get("title") or "").strip() or None,
            "author_id_hint": str(item.get("author_id") or "").strip() or None,
            "author_hint": str(item.get("author_name") or "").strip() or None,
            "published_hint": item.get("publish_time"),
            "last_reply_hint": item.get("club_topic_lastPostDate"),
            "reply_count": _integer(item.get("reply_count")),
            "video_id_hint": str(item.get("video_source") or "").strip() or None,
            "is_delete": _integer(item.get("is_delete")),
            "club_delete_flag": _integer(item.get("club_delete_flag")),
            "list_raw": {
                "club_is_poll": item.get("club_is_poll"),
                "club_is_video": item.get("club_is_video"),
                "club_topic_isPicture": item.get("club_topic_isPicture"),
            },
        }

    def validate_circle(self, circle_url: str) -> dict[str, Any]:
        """以真实列表首项及其详情同时验证论坛来源。"""

        source = parse_circle_url(circle_url)
        page = self._list_page(source, 1)
        if not page["items"]:
            raise CollectorFailure("CIRCLE_VALIDATION_FAILED", "汽车之家论坛没有返回可识别帖子。")
        candidate = self._candidate(source, page["items"][0], 0)
        record = self.fetch_post(candidate["url"], candidate=candidate)
        if record is None:
            raise CollectorFailure("CIRCLE_VALIDATION_FAILED", "论坛首条帖子未返回有效详情。")
        first = page["items"][0]
        name = str(first.get("club_bbs_name") or "").strip() if isinstance(first, dict) else ""
        return {
            "platform_code": self.code,
            "external_id": source.external_id,
            "name": name or f"汽车之家论坛 {source.external_id}",
            "url": source.url,
            "section": "dynamic",
            "sort": source.list_order,
            "sample_post_id": record["platform_post_id"],
            "adapter_version": self.adapter_version,
            "raw_status": dict(source.raw_status),
        }

    def discover_posts(
        self, circle_url: str, target_count: int, start_page: int = 1
    ) -> tuple[list[dict[str, Any]], str]:
        """按列表顺序分页发现并以帖子稳定 ID 去重。"""

        source = parse_circle_url(circle_url)
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        page_number = max(1, start_page)
        frozen_page_count: int | None = None
        source_index = 0
        while len(rows) < target_count:
            page = self._list_page(source, page_number)
            if frozen_page_count is None and page["items"] and page["total"] is not None:
                frozen_page_count = math.ceil(max(page["total"], 0) / PAGE_SIZE)
            if not page["items"]:
                return rows, "汽车之家列表没有返回更多帖子。"
            for raw in page["items"]:
                candidate = self._candidate(source, raw, source_index)
                source_index += 1
                if candidate["post_id"] in seen:
                    continue
                seen.add(candidate["post_id"])
                rows.append(candidate)
                if len(rows) >= target_count:
                    return rows, "达到配置的有效结果候选数量。"
            if frozen_page_count is not None and page_number >= frozen_page_count:
                return rows, "已经到达汽车之家论坛列表末页。"
            page_number += 1
        return rows, "达到配置的有效结果候选数量。"

    def fetch_post(
        self, post_url: str, *, candidate: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        """取得详情正文、媒体 ID 和第一页前十条一级回复。"""

        post_id, normalized_url = normalize_post_url(post_url)
        response = self._get(normalized_url)
        if int(response.status_code) == 404:
            return None
        if int(response.status_code) >= 400:
            raise CollectorFailure(
                "PLATFORM_HTTP_ERROR", f"汽车之家帖子详情返回 HTTP {response.status_code}。"
            )
        try:
            document = html.fromstring(response.content)
        except (TypeError, ValueError) as exc:
            raise CollectorFailure("PLATFORM_RESPONSE_INVALID", "汽车之家帖子 HTML 无法解析。") from exc
        source = response.content.decode("utf-8", errors="ignore")
        bbs_match = BBS_INFO_RE.search(source)
        topic_match = TOPIC_BLOCK_RE.search(source)
        if not bbs_match or not topic_match:
            raise CollectorFailure("PLATFORM_RESPONSE_INVALID", "汽车之家帖子缺少稳定身份数据。")
        try:
            bbs_info = json.loads(bbs_match.group("value"))
        except json.JSONDecodeError as exc:
            raise CollectorFailure("PLATFORM_RESPONSE_INVALID", "汽车之家论坛身份数据无效。") from exc
        topic_block = topic_match.group("body")
        observed_id = _js_int(topic_block, "topicId")
        if observed_id != int(post_id):
            raise CollectorFailure("POST_ID_MISMATCH", "汽车之家详情帖子 ID 与输入链接不一致。")
        bbs_id = _integer(bbs_info.get("bbsId"))
        bbs_type = str(bbs_info.get("bbs") or "").lower()
        if candidate and (
            bbs_id != candidate.get("bbs_id") or bbs_type != candidate.get("bbs_type")
        ):
            raise CollectorFailure("WRONG_POST", "汽车之家详情论坛身份与发现来源不符。")

        title_nodes = document.xpath(f"//*[{_class_tokens('post-title')}]")
        title = self._node_text(title_nodes[0]) if title_nodes else None
        title = title or _js_string(topic_block, "topicTitle")
        body_nodes = document.xpath(f"//*[{_class_tokens('post-container')}]")
        body = body_nodes[0] if body_nodes else None
        content = self._body_text(body) if body is not None else None
        image_urls = _unique_urls(body.xpath(".//img/@data-src") if body is not None else [])

        video_info: dict[str, Any] = {}
        video_match = VIDEO_INFO_RE.search(source)
        if video_match:
            try:
                decoded_video = json.loads(video_match.group("value"))
                if isinstance(decoded_video, dict):
                    video_info = decoded_video
            except json.JSONDecodeError as exc:
                raise CollectorFailure(
                    "PLATFORM_RESPONSE_INVALID", "汽车之家视频元数据无法解析。"
                ) from exc
        detail_video_ids = {
            str(value).strip()
            for value in document.xpath("//*[@data-vid]/@data-vid")
            if str(value).strip()
        }
        if video_info.get("videoid"):
            detail_video_ids.add(str(video_info["videoid"]).strip())
        if len(detail_video_ids) > 1:
            raise CollectorFailure("POST_VIDEO_ID_MISMATCH", "汽车之家详情视频 ID 相互冲突。")
        video_id = next(iter(detail_video_ids), None)
        hinted_video_id = str((candidate or {}).get("video_id_hint") or "").strip() or None
        if hinted_video_id and video_id != hinted_video_id:
            raise CollectorFailure("POST_VIDEO_ID_MISMATCH", "汽车之家列表与详情视频 ID 不一致。")

        author = _js_string(topic_block, "topicMemberName")
        author_id = _js_int(topic_block, "topicMemberId")
        publish_values = document.xpath(
            f"//*[{_class_tokens('post-handle-publish')}]//strong/text()"
        )
        published_at = next(
            (parsed for value in reversed(publish_values) if (parsed := _parse_platform_time(value))),
            None,
        )
        comments, reply_statuses = self._comments(document)
        topic_delete = _js_int(topic_block, "topicDelete")
        list_is_delete = (candidate or {}).get("is_delete")
        list_delete_flag = (candidate or {}).get("club_delete_flag")
        content_proven = bool(title or content or image_urls or video_id)
        visibility = (
            "visible"
            if content_proven
            and topic_delete == 0
            and list_is_delete == 0
            and list_delete_flag == 0
            else "unknown"
        )
        if not content_proven:
            raise CollectorFailure("POST_CONTENT_MISSING", "汽车之家帖子没有返回真实正文或媒体证明。")
        return {
            "platform_post_id": post_id,
            "url": normalized_url,
            "title": title,
            "author": author,
            "published_at": published_at,
            "content": content,
            "image_urls": image_urls,
            # 最终播放 URL 尚无真实合同，只保留 video_id 和元数据，不生成占位链接。
            "video_urls": [],
            "reply_count": (candidate or {}).get("reply_count"),
            "like_count": None,
            "section": "dynamic",
            "visibility": visibility,
            "raw_status": {
                "response_class": "post",
                "bbs_type": bbs_type,
                "bbs_id": bbs_id,
                "topic_delete": topic_delete,
                "list_is_delete": list_is_delete,
                "list_club_delete_flag": list_delete_flag,
                "topic_member_id": str(author_id) if author_id is not None else None,
                "video_id": video_id,
                "video_url_resolution": "not_verified" if video_id else None,
                "video_info": video_info or None,
                "reply_raw_statuses": reply_statuses,
                "source_raw": (candidate or {}).get("list_raw"),
            },
            "comments": comments,
        }

    @staticmethod
    def _node_text(node: Any) -> str | None:
        value = " ".join(str(node.text_content() or "").split()).strip()
        return value or None

    @classmethod
    def _body_text(cls, node: Any) -> str | None:
        """去除媒体与脚本节点后按页面文本片段顺序形成正文。"""

        values: list[str] = []
        for raw in node.xpath(".//text()[normalize-space()]"):
            value = " ".join(str(raw).replace("\xa0", " ").split()).strip()
            if value and value not in values:
                values.append(value)
        return "\n".join(values) or None

    @classmethod
    def _comments(cls, document: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """只读取 SSR 一级楼层，明确排除楼中楼接口与嵌套评论。"""

        rows = document.xpath(
            "//*[@id='js-reply-list-container']/li["
            + _class_tokens("js-reply-floor-container")
            + "]"
        )[:10]
        comments: list[dict[str, Any]] = []
        statuses: list[dict[str, Any]] = []
        for row in rows:
            reply_id = str(row.get("data-reply-id") or "").strip() or None
            member_id = str(row.get("data-member-id") or "").strip() or None
            detail_nodes = row.xpath(f".//*[{_class_tokens('reply-detail')}]")
            content = cls._node_text(detail_nodes[0]) if detail_nodes else None
            author = None
            for href in row.xpath(".//a[contains(@href, 'authorname=')]/@href"):
                match = re.search(r"(?:[?&])authorname=([^&]+)", str(href))
                if match:
                    author = unquote_plus(match.group(1)).strip() or None
                    break
            time_values = row.xpath(f".//*[{_class_tokens('reply-top')}]//strong/text()")
            published_at = next(
                (parsed for value in reversed(time_values) if (parsed := _parse_platform_time(value))),
                None,
            )
            like_values = row.xpath(
                f".//*[{_class_tokens('reply-bottom-praise')}]//strong/text()"
            )
            comments.append(
                {
                    "platform_comment_id": reply_id,
                    "author": author,
                    "content": content,
                    "published_at": published_at,
                    "like_count": _integer(like_values[0]) if like_values else None,
                }
            )
            statuses.append(
                {
                    "reply_id": reply_id,
                    "member_id": member_id,
                    "floor": str(row.get("data-floor") or "").strip() or None,
                    "status": str(row.get("data-status") or "").strip() or None,
                }
            )
        return comments, statuses

    def collect_circle(
        self,
        circle_url: str,
        target_count: int,
        skip_post_ids: set[str] | None = None,
        on_progress: ProgressCallback | None = None,
        on_page_evidence: PageEvidenceCallback | None = None,
    ) -> dict[str, Any]:
        """按有效详情数量继续翻页；页面截图能力当前明确关闭。"""

        if on_page_evidence is not None:
            raise CollectorFailure(
                "PAGE_EVIDENCE_UNSUPPORTED", "汽车之家当前尚未验证圈子页面截图合同。"
            )
        source = parse_circle_url(circle_url)
        records: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        seen = set(skip_post_ids or set())
        page_number = 1
        frozen_page_count: int | None = None
        source_index = 0
        exhausted = False
        while len(records) < target_count:
            page = self._list_page(source, page_number)
            if frozen_page_count is None and page["items"] and page["total"] is not None:
                frozen_page_count = math.ceil(max(page["total"], 0) / PAGE_SIZE)
            if not page["items"]:
                exhausted = True
                break
            candidates: list[dict[str, Any]] = []
            for raw in page["items"]:
                try:
                    candidate = self._candidate(source, raw, source_index)
                except CollectorFailure as exc:
                    raw_url = raw.get("pc_url") if isinstance(raw, dict) else source.url
                    failure = {
                        "url": str(raw_url or source.url),
                        "code": exc.code,
                        "message": exc.message,
                        "source_index": source_index,
                    }
                    failures.append(failure)
                    if on_progress:
                        on_progress(None, failure)
                    source_index += 1
                    continue
                source_index += 1
                if candidate["post_id"] in seen:
                    continue
                seen.add(candidate["post_id"])
                candidates.append(candidate)

            cursor = 0
            while cursor < len(candidates) and len(records) < target_count:
                batch = candidates[cursor : cursor + min(self.concurrency, target_count - len(records))]
                cursor += len(batch)

                def fetch(value: dict[str, Any]) -> tuple[dict[str, Any], Any, Any]:
                    try:
                        return value, self.fetch_post(value["url"], candidate=value), None
                    except (AuthenticationRequired, CollectorFailure) as exc:
                        return value, None, exc

                with ThreadPoolExecutor(max_workers=max(1, len(batch))) as pool:
                    outcomes = list(pool.map(fetch, batch))
                for candidate, record, error in outcomes:
                    if isinstance(error, AuthenticationRequired):
                        raise AuthenticationRequired(
                            error.message,
                            trigger_url=candidate["url"],
                            records=records,
                            failures=failures,
                        ) from error
                    if isinstance(error, CollectorFailure) or record is None:
                        failure = {
                            "url": candidate["url"],
                            "code": error.code if isinstance(error, CollectorFailure) else "POST_NOT_FOUND",
                            "message": (
                                error.message
                                if isinstance(error, CollectorFailure)
                                else "帖子详情当前不可用。"
                            ),
                            "source_index": candidate["order_index"],
                        }
                        failures.append(failure)
                        if on_progress:
                            on_progress(None, failure)
                        continue
                    record["order_index"] = candidate["order_index"]
                    records.append(record)
                    if on_progress:
                        on_progress(record, None)
            if frozen_page_count is not None and page_number >= frozen_page_count:
                exhausted = True
                break
            page_number += 1
        if len(records) >= target_count:
            stop_reason = "已经取得配置数量的有效帖子。"
        elif exhausted:
            stop_reason = "汽车之家论坛没有更多可用内容，按实际有效数量结束。"
        else:
            stop_reason = "候选帖子存在错误，未能取得配置数量的有效结果。"
        return {"records": records, "failures": failures, "stop_reason": stop_reason}

    def collect_urls(
        self, urls: list[str], on_progress: ProgressCallback | None = None
    ) -> dict[str, Any]:
        """规范化、去重并逐条处理已知汽车之家帖子 URL。"""

        records: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        seen: set[str] = set()
        for source_index, raw_url in enumerate(urls):
            try:
                post_id, normalized = normalize_post_url(raw_url)
            except CollectorFailure as exc:
                failure = {
                    "url": raw_url,
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
            except CollectorFailure as exc:
                failure = {
                    "url": normalized,
                    "code": exc.code,
                    "message": exc.message,
                    "source_index": source_index,
                }
                failures.append(failure)
                if on_progress:
                    on_progress(None, failure)
                continue
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
