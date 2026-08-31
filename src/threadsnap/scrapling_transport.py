"""基于 Scrapling FetcherSession 的统一同步 HTTP 传输层。"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import urlsplit

from scrapling.fetchers import FetcherSession

# FetcherSession 默认以 INFO 输出完整请求 URL；平台查询参数可能包含签名或业务身份，
# 正式服务只保留警告及错误，避免普通请求明细进入控制台和服务日志。
logging.getLogger("scrapling").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _BrowserCookie:
    """保留浏览器 Cookie 的作用域，避免跨平台域名泄漏。"""

    name: str
    value: str
    domain: str
    path: str
    secure: bool
    expires: float | None

    def matches(self, url: str, now: float) -> bool:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
        domain = self.domain.lstrip(".").lower()
        request_path = parsed.path or "/"
        if not domain or not (host == domain or host.endswith(f".{domain}")):
            return False
        if self.secure and parsed.scheme.lower() != "https":
            return False
        if self.expires is not None and self.expires > 0 and self.expires <= now:
            return False
        cookie_path = self.path or "/"
        return request_path == cookie_path or request_path.startswith(
            cookie_path.rstrip("/") + "/"
        )


class BrowserCookieStore:
    """线程安全地保存 storage state 与运行期生成的 Cookie。"""

    def __init__(self, storage_state: dict[str, Any] | None = None) -> None:
        self._lock = threading.RLock()
        self._cookies: list[_BrowserCookie] = []
        for item in (storage_state or {}).get("cookies", []):
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "")
            value = item.get("value")
            domain = str(item.get("domain") or "")
            if not name or not isinstance(value, str) or not domain:
                continue
            expires = item.get("expires")
            self.set(
                name,
                value,
                domain=domain,
                path=str(item.get("path") or "/"),
                secure=bool(item.get("secure")),
                expires=float(expires) if isinstance(expires, (int, float)) else None,
            )

    def set(
        self,
        name: str,
        value: str,
        *,
        domain: str,
        path: str = "/",
        secure: bool = False,
        expires: float | None = None,
    ) -> None:
        """按名称、域和路径覆盖 Cookie，其余同名作用域保持独立。"""

        cookie = _BrowserCookie(name, value, domain, path or "/", secure, expires)
        key = (name, domain.lower(), cookie.path)
        with self._lock:
            self._cookies = [
                item
                for item in self._cookies
                if (item.name, item.domain.lower(), item.path) != key
            ]
            self._cookies.append(cookie)

    def get(self, name: str, default: str | None = None) -> str | None:
        """返回同名 Cookie 的最后写入值，供平台身份门禁读取。"""

        now = time.time()
        with self._lock:
            for item in reversed(self._cookies):
                if item.name == name and not (
                    item.expires is not None and item.expires > 0 and item.expires <= now
                ):
                    return item.value
        return default

    def for_url(self, url: str) -> dict[str, str]:
        """只返回与目标 URL 域、路径、协议和有效期匹配的 Cookie。"""

        now = time.time()
        with self._lock:
            matches = sorted(
                (item for item in self._cookies if item.matches(url, now)),
                key=lambda item: (len(item.domain.lstrip(".")), len(item.path)),
            )
            return {
                item.name: item.value
                for item in matches
            }


class ScraplingHttpResponse:
    """把 Scrapling 响应收敛为采集器既有的最小响应合同。"""

    def __init__(self, response: Any) -> None:
        self._response = response
        self.status_code = int(response.status)
        self.content = bytes(response.body)
        self.url = str(response.url)
        self.headers = response.headers
        self.history = list(getattr(response, "history", []) or [])

    @property
    def text(self) -> str:
        """按响应声明编码解码；缺失或无效时使用 UTF-8 替换模式。"""

        encoding = getattr(self._response, "encoding", None)
        if not isinstance(encoding, str) or not encoding:
            content_type = str(self.headers.get("content-type", ""))
            marker = "charset="
            encoding = (
                content_type.lower().split(marker, 1)[1].split(";", 1)[0].strip()
                if marker in content_type.lower()
                else "utf-8"
            )
        try:
            return self.content.decode(encoding, errors="replace")
        except LookupError:
            return self.content.decode("utf-8", errors="replace")

    def json(self) -> Any:
        """从原始响应字节解析 JSON，避免依赖 HTML 文本节点语义。"""

        return json.loads(self.text)


class ScraplingHttpSession:
    """单线程持有一个 FetcherSession，并向现有采集器暴露 get/post。"""

    def __init__(
        self,
        cookies: BrowserCookieStore,
        *,
        timeout_seconds: int,
        impersonate: str,
    ) -> None:
        self.cookies = cookies
        self._manager = FetcherSession(
            impersonate=impersonate,
            stealthy_headers=False,
            timeout=timeout_seconds,
            retries=1,
            follow_redirects=True,
        )
        self._client = self._manager.__enter__()
        self._closed = False

    def request(self, method: str, url: str, **kwargs: Any) -> ScraplingHttpResponse:
        """执行一次请求；业务重试仍由平台适配器显式控制。"""

        allow_redirects = kwargs.pop("allow_redirects", None)
        if allow_redirects is not None:
            kwargs["follow_redirects"] = bool(allow_redirects)
        browser_cookies = self.cookies.for_url(url)
        explicit_cookies = kwargs.pop("cookies", None)
        if isinstance(explicit_cookies, Mapping):
            browser_cookies.update(
                {str(key): str(value) for key, value in explicit_cookies.items()}
            )
        if browser_cookies:
            kwargs["cookies"] = browser_cookies
        request_method = getattr(self._client, method.lower(), None)
        if not callable(request_method):
            raise ValueError(f"Scrapling FetcherSession 不支持请求方法：{method}")
        response = request_method(url, **kwargs)
        return ScraplingHttpResponse(response)

    def get(self, url: str, **kwargs: Any) -> ScraplingHttpResponse:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> ScraplingHttpResponse:
        return self.request("POST", url, **kwargs)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._manager.__exit__(None, None, None)


class ScraplingHttpPool:
    """为每个采集线程提供独立 Scrapling Session，并统一关闭资源。"""

    def __init__(
        self,
        storage_state: dict[str, Any] | None,
        *,
        timeout_seconds: int,
        impersonate: str = "chrome",
    ) -> None:
        self.cookies = BrowserCookieStore(storage_state)
        self.timeout_seconds = timeout_seconds
        self.impersonate = impersonate
        self._thread_local = threading.local()
        self._lock = threading.Lock()
        self._sessions: list[ScraplingHttpSession] = []
        self._closed = False

    def session(self) -> ScraplingHttpSession:
        if self._closed:
            raise RuntimeError("Scrapling HTTP 资源池已经关闭。")
        session = getattr(self._thread_local, "session", None)
        if session is None:
            session = ScraplingHttpSession(
                self.cookies,
                timeout_seconds=self.timeout_seconds,
                impersonate=self.impersonate,
            )
            self._thread_local.session = session
            with self._lock:
                self._sessions.append(session)
        return session

    def close(self) -> None:
        """关闭所有已创建的线程 Session；重复调用保持幂等。"""

        with self._lock:
            self._closed = True
            sessions, self._sessions = self._sessions, []
        for session in sessions:
            try:
                session.close()
            except Exception:
                logger.warning("关闭 Scrapling HTTP Session 失败。", exc_info=True)
