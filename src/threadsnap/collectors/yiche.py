"""易车社区列表、帖子详情和一级评论适配器。"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from math import ceil
from typing import Any, Callable, Iterable
from urllib.parse import parse_qs, urljoin, urlsplit
from zoneinfo import ZoneInfo

from json_repair import repair_json
from lxml import html

from ..scrapling_transport import ExecutionScopeKey, ScraplingHttpPool
from .base import AuthenticationRequired, CircleSource, CollectorFailure

BASE_URL = "https://baa.yiche.com"
ADAPTER_VERSION = "yiche-community-v7-control-recovery"
CIRCLE_RE = re.compile(
    r"^/(?P<id>[A-Za-z0-9_-]+)/?"
    r"(?:index-0-(?P<order>[01])-(?P<page>\d+)\.html)?/?$"
)
POST_RE = re.compile(r"^/(?P<circle>[A-Za-z0-9_-]+)/thread-(?P<id>\d+)\.html/?$")
WAF_MARKERS = ("TencentCaptcha", "TCaptcha.js", "/WafCaptcha", "__captcha")
PUA_RE = re.compile("[\ue000-\uf8ff]")
YICHE_TIMEZONE = ZoneInfo("Asia/Shanghai")
ProgressCallback = Callable[[dict[str, Any] | None, dict[str, Any] | None], None]

# 易车 PC 网页公开脚本 index-V311.min.js 的当前请求协议。任何协议变更都必须
# 通过样本重新验证后升级版本，不能静默接受未知签名或挑战页面。
YICHE_API_PROTOCOL = "pc-v311"
YICHE_API_CID = "508"
YICHE_API_SIGN_KEY = "19DDD1FBDFF065D3A4DA777D2D7A81EC"
YICHE_CHALLENGE_KEY = "tg09It3*9h"
YICHE_COMMENT_CONTENT_TYPE = 56
ACCOUNT_COOKIE_NAME = "username"
INTERRUPTING_CONTROL_CODES = {
    "PLATFORM_CAPTCHA_REQUIRED",
    "PLATFORM_CHALLENGE",
    "PLATFORM_RATE_LIMITED",
}


@dataclass(frozen=True)
class ApiEvent:
    """页面本次导航产生的业务响应及其脱敏身份。"""

    path: str
    status: int
    payload: Any
    content_id: str | None = None


@dataclass(frozen=True)
class CommentResult:
    """帖子可用时保留的一级评论结果，不把评论响应作为整帖有效性门禁。"""

    comments: list[dict[str, Any]]
    termination: str
    verified: bool = True


def _request_content_id(url: str, post_data: str | None = None) -> str | None:
    """从查询或表单中的 param JSON 提取帖子身份，用于合同测试与诊断。"""

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


def _rc4_bytes(key: str, value: str) -> bytes:
    """实现平台 203 控制文档公开声明的 RC4 计算，不执行页面脚本。"""

    state = list(range(256))
    key_bytes = key.encode("utf-8")
    value_bytes = value.encode("utf-8")
    cursor = 0
    for index in range(256):
        cursor = (cursor + state[index] + key_bytes[index % len(key_bytes)]) % 256
        state[index], state[cursor] = state[cursor], state[index]
    left = cursor = 0
    output = bytearray()
    for item in value_bytes:
        left = (left + 1) % 256
        cursor = (cursor + state[left]) % 256
        state[left], state[cursor] = state[cursor], state[left]
        output.append(item ^ state[(state[left] + state[cursor]) % 256])
    return bytes(output)


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
        raise CollectorFailure(
            "PLATFORM_CAPTCHA_REQUIRED",
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
    """易车账号 Session 门禁与直连 HTTP 列表、详情、评论适配器。"""

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
        execution_scope: ExecutionScopeKey | None = None,
    ):
        del browser_headless
        self.storage_state = storage_state
        self.concurrency = max(1, concurrency)
        self.timeout_seconds = timeout_seconds
        self.semaphore = threading.BoundedSemaphore(self.concurrency)
        self.http = ScraplingHttpPool(
            storage_state,
            timeout_seconds=timeout_seconds,
            scope=(execution_scope or ExecutionScopeKey()).bind_platform("yiche"),
        )
        self.cookies = self.http.cookies
        self.user_guid = self.cookies.get("UserGuid") or self.cookies.get("CIGUID")
        if not self.user_guid:
            self.user_guid = str(uuid.uuid4())
            self.cookies.set("CIGUID", self.user_guid, domain=".yiche.com", path="/")
        self._account_verified = False

    def _http_session(self) -> Any:
        """返回当前线程独享的 Scrapling FetcherSession 适配器。"""

        return self.http.session()

    def _get(self, url: str, **kwargs: Any) -> Any:
        """有界重试直连请求；平台业务状态由上层按响应类型分类。"""
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                with self.semaphore:
                    response = self._http_session().get(
                        url, timeout=self.timeout_seconds, allow_redirects=True, **kwargs
                    )
                if response.status_code >= 500:
                    last_error = RuntimeError(f"HTTP {response.status_code}")
                    if attempt < 2:
                        time.sleep(0.5 * (attempt + 1))
                        continue
                    break
                return response
            except Exception as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(0.5 * (attempt + 1))
        raise CollectorFailure("PLATFORM_NETWORK_ERROR", f"访问易车失败：{last_error}")

    def close(self) -> None:
        """关闭采集线程创建的全部 Scrapling Session。"""

        self.http.close()

    @staticmethod
    def _challenge_cookie(content: str) -> tuple[str, str]:
        """严格解析当前 203 控制文档；未知脚本结构直接停止而不是执行脚本。"""
        patterns = {
            "xvasu": r"var\s+_xvasu\s*=\s*(\d+)\s*;",
            "xvpfs": r"var\s+_xvpfs\s*=\s*[\"']([A-Za-z0-9_-]{1,32})[\"']\s*;",
            "xvpts": r"var\s+_xvpts\s*=\s*([0-9]+(?:\.[0-9]+)?)\s*;",
        }
        values: dict[str, str] = {}
        for name, pattern in patterns.items():
            match = re.search(pattern, content)
            if not match:
                raise CollectorFailure(
                    "YICHE_CHALLENGE_CHANGED", "易车详情控制文档结构已变化，本次请求已停止。"
                )
            values[name] = match.group(1)
        if "btoa(" not in content or "window['location']" not in content:
            raise CollectorFailure(
                "YICHE_CHALLENGE_CHANGED", "易车详情控制文档缺少已验证的重载边界，本次请求已停止。"
            )
        cookie_name = values["xvpfs"] + values["xvasu"]
        cookie_value = base64.b64encode(
            _rc4_bytes(YICHE_CHALLENGE_KEY, f"{values['xvpts']}:{values['xvasu']}")
        ).decode("ascii")
        return cookie_name, cookie_value

    def _document(self, url: str) -> tuple[str, str]:
        """直连详情页，并用按需 Stealthy 通道处理浏览器可解除的保护。"""
        observed_generation = self.http.recovery_generation
        response = self._get(url, headers={"Referer": BASE_URL + "/"})
        challenge_cookie_applied = False
        if response.status_code == 203:
            cookie_name, cookie_value = self._challenge_cookie(response.text)
            host = urlsplit(url).hostname or "baa.yiche.com"
            self._http_session().cookies.set(cookie_name, cookie_value, domain=host, path="/")
            response = self._get(url, headers={"Referer": BASE_URL + "/"})
            challenge_cookie_applied = True
        if response.status_code == 429:
            raise CollectorFailure(
                "PLATFORM_RATE_LIMITED",
                "易车页面返回限流状态，请稍后重试。",
                trigger_url=url,
            )
        if response.status_code == 403 and challenge_cookie_applied:
            raise CollectorFailure(
                "PLATFORM_CHALLENGE",
                "易车详情挑战校验后仍拒绝访问，请在服务器浏览器完成访问验证。",
                trigger_url=url,
            )
        if response.status_code in {401, 403}:
            raise AuthenticationRequired("易车登录 Session 已失效。", trigger_url=url)
        if response.status_code != 200:
            raise CollectorFailure("HTTP_ERROR", f"易车页面返回 HTTP {response.status_code}。")
        try:
            require_content_page(response.text, url=url)
        except CollectorFailure as exc:
            if exc.code != "PLATFORM_CAPTCHA_REQUIRED":
                raise
            try:
                recovery = self.http.recover_protected(url, observed_generation=observed_generation)
            except Exception:
                recovery = None
            if recovery is None or not recovery.should_retry_http:
                raise
            response = self._get(url, headers={"Referer": BASE_URL + "/"})
            if response.status_code == 429:
                raise CollectorFailure(
                    "PLATFORM_RATE_LIMITED",
                    "易车页面返回限流状态，请稍后重试。",
                    trigger_url=url,
                )
            if response.status_code == 401:
                raise AuthenticationRequired("易车登录 Session 已失效。", trigger_url=url)
            if response.status_code == 403:
                raise CollectorFailure(
                    "PLATFORM_CHALLENGE",
                    "易车受保护页面经一次浏览器恢复后仍拒绝访问，请完成访问验证。",
                    trigger_url=url,
                )
            if response.status_code != 200:
                raise CollectorFailure("HTTP_ERROR", f"易车页面返回 HTTP {response.status_code}。")
            require_content_page(response.text, url=url)
            self.http.confirm_protected_recovery(recovery.generation)
        return response.text, str(response.url)

    @staticmethod
    def _signed_request(
        data: dict[str, Any], timestamp: int
    ) -> tuple[dict[str, str], dict[str, str]]:
        """按当前公开 PC 协议生成稳定查询参数与签名头。"""
        param = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        source = f"cid={YICHE_API_CID}&param={param}{YICHE_API_SIGN_KEY}{timestamp}"
        headers = {
            "x-platform": "pc",
            "x-timestamp": str(timestamp),
            "x-sign": hashlib.md5(source.encode("utf-8")).hexdigest(),
        }
        return {"cid": YICHE_API_CID, "param": param}, headers

    def _api_event(
        self, url: str, data: dict[str, Any], *, referer: str, content_id: str | None = None
    ) -> ApiEvent:
        timestamp = int(time.time() * 1000)
        params, headers = self._signed_request(data, timestamp)
        headers.update({"Referer": referer, "x-user-guid": self.user_guid})
        response = self._get(url, params=params, headers=headers)
        payload: Any = None
        try:
            payload = response.json()
        except Exception:
            pass
        return ApiEvent(urlsplit(str(response.url)).path, response.status_code, payload, content_id)

    @staticmethod
    def _api_payload(
        events: list[ApiEvent],
        path_suffix: str,
        *,
        required: bool = True,
        expected_content_id: str | None = None,
    ) -> dict[str, Any] | None:
        """校验直连业务响应、业务码与帖子身份。"""
        matched = [item for item in events if item.path.lower().endswith(path_suffix.lower())]
        if not matched:
            if required:
                raise CollectorFailure("API_RESPONSE_MISSING", "易车未返回预期业务响应。")
            return None
        event = matched[-1]
        if event.status == 429:
            raise CollectorFailure(
                "PLATFORM_RATE_LIMITED", "易车接口返回限流状态，请稍后重试。"
            )
        if event.status in {401, 403}:
            raise AuthenticationRequired("易车登录 Session 已失效。")
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
                "COMMENTS_IDENTITY_MISMATCH", "易车一级评论请求未绑定当前帖子身份。"
            )
        return payload

    def _require_account_cookie(self) -> None:
        if not self.cookies.get(ACCOUNT_COOKIE_NAME):
            raise AuthenticationRequired(
                "易车当前没有账号登录信息，请先完成易车登录认证。",
                trigger_url="https://i.yiche.com/authenservice/login.html",
            )

    def _ensure_account_identity(self, probe_url: str = BASE_URL + "/") -> None:
        """每个采集器实例只做一次真实账号门禁，后续请求仍分类会话失效。"""

        if self._account_verified:
            return
        self._require_account_cookie()
        event = self._api_event(
            "https://mapi.yiche.com/web_api/user_center_api/api/v1/message/get_message_num",
            {},
            referer=probe_url,
        )
        payload = self._api_payload([event], "/message/get_message_num")
        data = payload.get("data") if payload else None
        if not isinstance(data, dict) or not data.get("userId"):
            raise AuthenticationRequired(
                "易车账号身份接口未返回用户身份，请重新登录。",
                trigger_url="https://i.yiche.com/authenservice/login.html",
            )
        self._account_verified = True

    def validate_auth(self, probe_url: str) -> dict[str, Any]:
        """以账号 Cookie 和官方用户消息接口双重证明登录身份。"""

        self._ensure_account_identity(probe_url)
        return {"platform": self.code, "account_login_verified": True}

    def _list_page(self, source: CircleSource, page_number: int) -> dict[str, Any]:
        """用公开网页同款签名直接请求圈子身份和帖子列表。"""
        order = 1 if source.list_order == "latest_publish" else 0
        referer = f"{BASE_URL}/{source.external_id}/index-0-{order}-{page_number}.html"
        lookup = self._api_event(
            "https://mgw.yiche.com/web_api/web_forum/api/pc/forum/getid",
            {"seoName": source.external_id},
            referer=referer,
        )
        lookup_payload = self._api_payload([lookup], "/forum/getid")
        forum_id = _integer(lookup_payload.get("data") if lookup_payload else None)
        if not forum_id:
            raise CollectorFailure("CIRCLE_IDENTITY_MISMATCH", "易车社区短名没有返回稳定圈子身份。")
        forum_event = self._api_event(
            "https://mgw.yiche.com/web_api/web_forum/api/pc/forum/get",
            {"forumId": forum_id},
            referer=referer,
        )
        list_event = self._api_event(
            "https://mgw.yiche.com/web_api/web_forum/api/pc/post/getlist",
            {
                "forumId": forum_id,
                "order": order,
                "pageIndex": page_number,
                "pageSize": 50,
                "tagId": -1,
            },
            referer=referer,
        )
        forum_payload = self._api_payload([forum_event], "/forum/get")
        list_payload = self._api_payload([list_event], "/post/getlist")
        data = list_payload.get("data") if list_payload else None
        if not isinstance(data, dict) or not isinstance(data.get("list"), list):
            raise CollectorFailure("LIST_RESPONSE_INVALID", "易车帖子列表响应结构无效。")
        forum = forum_payload.get("data") if forum_payload else None
        return {
            **data,
            "forum": forum if isinstance(forum, dict) else None,
            "forum_id_lookup": forum_id,
        }

    def validate_circle(self, circle_url: str) -> dict[str, Any]:
        self._ensure_account_identity(circle_url)
        source = parse_circle_url(circle_url)
        page = self._list_page(source, 1)
        rows = page.get("list") or []
        if not rows:
            raise CollectorFailure("CIRCLE_VALIDATION_FAILED", "易车社区没有返回可验证的帖子。")
        first = rows[0] if isinstance(rows[0], dict) else {}
        forum_id = _integer(first.get("forumId"))
        forum_name = str(first.get("forumName") or "").strip()
        seo_name = str(first.get("forumApp") or "").strip()
        forum = page.get("forum") or {}
        if not forum_id or _integer(page.get("forum_id_lookup")) != forum_id:
            raise CollectorFailure("CIRCLE_IDENTITY_MISMATCH", "易车社区与列表帖子身份不一致。")
        if (
            not forum_name
            or not seo_name
            or seo_name.lower() != source.external_id.lower()
            or _integer(forum.get("id")) != forum_id
            or str(forum.get("forumApp") or "").strip().lower() != seo_name.lower()
            or str(forum.get("name") or "").strip() != forum_name
        ):
            raise CollectorFailure("CIRCLE_IDENTITY_MISMATCH", "易车社区短名与稳定身份不一致。")
        first_url = f"{BASE_URL}/{source.external_id}/thread-{first.get('id')}.html"
        self._fetch_post(first_url, list_row=first)
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
            raise CollectorFailure(
                "POST_CONTENT_OBFUSCATED", "易车详情正文仍含未还原的私有区字符。"
            )
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
            "author": str(author.get("name") or root[0].get("data-name") or "").strip() or None,
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

        try:
            payload = self._api_payload(
                events,
                "/comment/top_comment_list",
                required=False,
                expected_content_id=expected_content_id,
            )
        except CollectorFailure as exc:
            if exc.code in INTERRUPTING_CONTROL_CODES:
                raise
            return CommentResult([], "first_page", verified=False)
        comments: list[dict[str, Any]] = []
        if payload:
            data = payload.get("data")
            if not isinstance(data, dict) or not isinstance(data.get("list"), list):
                return CommentResult([], "first_page", verified=False)
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
            if have_next is False or (have_next is None and count_proves_terminal):
                return CommentResult(
                    comments,
                    "have_next_false" if have_next is False else "count_boundary",
                )
            return CommentResult(comments, "first_page")
        del content, reply_count
        return CommentResult([], "first_page", verified=False)

    def _fetch_post(
        self, post_url: str, *, list_row: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        expected_circle, expected_id, normalized_url = _post_identity(post_url)
        content, final_url = self._document(normalized_url)
        final_circle, final_id, _ = _post_identity(final_url)
        if final_id != expected_id or final_circle.lower() != expected_circle.lower():
            raise CollectorFailure("POST_IDENTITY_MISMATCH", "易车详情最终地址与请求帖子不一致。")
        record = self._detail_payload(content, normalized_url)
        row = list_row or {}
        row_id = str(row.get("id") or "")
        row_circle = str(row.get("forumApp") or "").strip()
        if row_id and (row_id != expected_id or row_circle.lower() != expected_circle.lower()):
            raise CollectorFailure("POST_IDENTITY_MISMATCH", "易车列表与详情帖子身份不一致。")
        if record["reply_count"] is None:
            record["reply_count"] = _integer(row.get("repliesNum"))
        comment_event = self._api_event(
            "https://mapi.yiche.com/web_api/information_api/api/v1/comment/top_comment_list",
            {
                "contentType": YICHE_COMMENT_CONTENT_TYPE,
                "contentId": expected_id,
                "currentPage": 1,
                "pageSize": 20,
                "hotFlag": True,
                "findStartTime": None,
                "diffCommnetId": None,
                "userCommentIds": None,
                "timeClickFlag": False,
            },
            referer=normalized_url,
            content_id=expected_id,
        )
        try:
            comment_result = self._parse_comments(
                content, [comment_event], record["reply_count"], expected_id
            )
        except CollectorFailure as exc:
            exc.trigger_url = exc.trigger_url or normalized_url
            raise
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
            "comment_capture": comment_result.termination,
            "transport": "direct_http",
            "api_protocol": YICHE_API_PROTOCOL,
        }
        if not record["content"] and not record["image_urls"] and not record["video_urls"]:
            raise CollectorFailure("POST_CONTENT_EMPTY", "易车详情没有返回正文或媒体。")
        record["visibility"] = "visible"
        return record

    def fetch_post(
        self, post_url: str, *, list_row: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """通过直连 HTTP 取得单个帖子，不启动 Chromium。"""
        self._ensure_account_identity(post_url)
        return self._fetch_post(post_url, list_row=list_row)

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
        self._ensure_account_identity(circle_url)
        source = parse_circle_url(circle_url)
        records: list[dict[str, Any]] = []
        failures: list[dict[str, str]] = []
        seen = set(skip_post_ids or set())
        candidate_ids: set[str] = set()
        page_number = 1
        frozen_total: int | None = None
        source_index = 0
        selected_count = 0
        stop_reason = "易车列表已经没有更多帖子。"
        while selected_count < target_count:
            page = self._list_page(source, page_number)
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
                if selected_count >= target_count:
                    break
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
                selected_count += 1
                url = f"{BASE_URL}/{source.external_id}/thread-{post_id}.html"
                try:
                    record = self._fetch_post(url, list_row=row)
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
                    if exc.code in INTERRUPTING_CONTROL_CODES:
                        exc.trigger_url = exc.trigger_url or url
                        raise
                    failure = {
                        "url": url,
                        "code": exc.code,
                        "message": exc.message,
                        "source_index": str(index),
                    }
                    failures.append(failure)
                    if on_progress:
                        on_progress(None, failure)
            if selected_count >= target_count:
                break
            if page_number * 50 >= frozen_total:
                break
            if new_candidates == 0:
                stop_reason = "易车列表分页没有返回新的帖子身份。"
                break
            page_number += 1
        if selected_count >= target_count and failures:
            stop_reason = "固定候选中存在未完成帖子，未使用后续帖子替换。"
        elif selected_count >= target_count:
            stop_reason = "已经处理配置数量的固定候选帖子。"
        return {"records": records, "failures": failures, "stop_reason": stop_reason}

    def collect_urls(
        self, urls: list[str], *, on_progress: ProgressCallback | None = None
    ) -> dict[str, Any]:
        self._ensure_account_identity(urls[0] if urls else BASE_URL + "/")
        records: list[dict[str, Any]] = []
        failures: list[dict[str, str]] = []
        seen: set[str] = set()
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
                record = self._fetch_post(normalized_url)
                record["order_index"] = source_index
                records.append(record)
                if on_progress:
                    on_progress(record, None)
            except AuthenticationRequired as exc:
                exc.records = records
                exc.failures = failures
                raise
            except CollectorFailure as exc:
                if exc.code in INTERRUPTING_CONTROL_CODES:
                    exc.trigger_url = exc.trigger_url or normalized_url
                    raise
                failure = {
                    "url": normalized_url,
                    "code": exc.code,
                    "message": exc.message,
                    "source_index": str(source_index),
                }
                failures.append(failure)
                if on_progress:
                    on_progress(None, failure)
        return {"records": records, "failures": failures, "stop_reason": "URL 清单处理完成。"}
