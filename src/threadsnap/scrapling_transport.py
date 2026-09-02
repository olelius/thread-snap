"""Scrapling 普通 HTTP 与受保护浏览器的统一同步传输层。"""

from __future__ import annotations

import json
import logging
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Iterator, Mapping
from urllib.parse import urlsplit

from scrapling.fetchers import FetcherSession, StealthySession

# FetcherSession 默认以 INFO 输出完整请求 URL；平台查询参数可能包含签名或业务身份，
# 正式服务只保留警告及错误，避免普通请求明细进入控制台和服务日志。
logging.getLogger("scrapling").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExecutionScopeKey:
    """标识一次传输资源所属范围，当前默认值对应单用户运行。"""

    platform: str = "shared"
    owner: str = "single-user"
    credential: str = "default"

    def __post_init__(self) -> None:
        if not self.platform or not self.owner or not self.credential:
            raise ValueError("执行作用域各部分均须为非空字符串。")

    @property
    def value(self) -> str:
        """返回仅用于内存资源协调的稳定键，不进入请求或持久化数据。"""

        return f"{self.owner}:{self.platform}:{self.credential}"

    def bind_platform(self, platform: str) -> ExecutionScopeKey:
        """把通用调用方作用域绑定到适配器平台，并拒绝跨平台误用。"""

        if self.platform not in {"shared", platform}:
            raise ValueError("执行作用域平台与采集器平台不一致。")
        return ExecutionScopeKey(
            platform=platform,
            owner=self.owner,
            credential=self.credential,
        )


@dataclass(frozen=True)
class ProtectionNavigationPolicy:
    """集中保存保护页浏览器策略，避免适配器重复拼装参数。"""

    disable_resources: bool = False
    load_dom: bool = True
    network_idle: bool = False
    post_navigation_wait_ms: int = 0


@dataclass(frozen=True)
class BrowserResourceSnapshot:
    """进程级浏览器许可的无敏感信息运行快照。"""

    maximum: int
    active: int
    peak: int
    waiting: int
    acquisitions: int


class BrowserResourceBudget:
    """跨资源池限制同时运行的 Stealthy 浏览器数量。"""

    def __init__(self, maximum: int = 1) -> None:
        if maximum < 1:
            raise ValueError("浏览器资源上限必须为正整数。")
        self.maximum = maximum
        self._semaphore = threading.BoundedSemaphore(maximum)
        self._lock = threading.Lock()
        self._active = 0
        self._peak = 0
        self._waiting = 0
        self._acquisitions = 0

    @contextmanager
    def lease(self, _scope: ExecutionScopeKey) -> Iterator[None]:
        """取得一个进程级浏览器许可，并在退出时可靠归还。"""

        with self._lock:
            self._waiting += 1
        self._semaphore.acquire()
        with self._lock:
            self._waiting -= 1
            self._active += 1
            self._peak = max(self._peak, self._active)
            self._acquisitions += 1
        try:
            yield
        finally:
            with self._lock:
                self._active -= 1
            self._semaphore.release()

    def snapshot(self) -> BrowserResourceSnapshot:
        """返回当前计数，供运行诊断和资源回归使用。"""

        with self._lock:
            return BrowserResourceSnapshot(
                maximum=self.maximum,
                active=self._active,
                peak=self._peak,
                waiting=self._waiting,
                acquisitions=self._acquisitions,
            )


@dataclass(frozen=True)
class ProtectionRecoveryResult:
    """描述一次保护页导航尝试；成功仍须由原业务请求确认。"""

    generation: int
    attempted: bool
    should_retry_http: bool
    browser_status: int | None
    elapsed_seconds: float
    error_type: str | None = None

    @property
    def reused(self) -> bool:
        """表示当前调用是否复用了同一控制事件的既有导航结果。"""

        return not self.attempted


@dataclass(frozen=True)
class ScraplingTransportSnapshot:
    """单个资源池的轻量运行指标。"""

    scope: str
    http_requests: int
    http_rotations: int
    browser_attempts: int
    browser_reuses: int
    browser_usable_responses: int
    browser_failures: int
    confirmed_recoveries: int
    attempt_generation: int
    verified_generation: int


_DEFAULT_BROWSER_BUDGET = BrowserResourceBudget(maximum=1)


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
        return request_path == cookie_path or request_path.startswith(cookie_path.rstrip("/") + "/")


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
                item for item in self._cookies if (item.name, item.domain.lower(), item.path) != key
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
            return {item.name: item.value for item in matches}

    def browser_cookies(self) -> list[dict[str, Any]]:
        """导出仍有效的 Playwright Cookie，供隐身浏览器继承同一身份。"""

        now = time.time()
        with self._lock:
            return [
                {
                    "name": item.name,
                    "value": item.value,
                    "domain": item.domain,
                    "path": item.path or "/",
                    "secure": item.secure,
                    "expires": item.expires if item.expires is not None else -1,
                }
                for item in self._cookies
                if not (item.expires is not None and item.expires > 0 and item.expires <= now)
            ]

    def update_from_browser(self, cookies: list[dict[str, Any]]) -> None:
        """合并浏览器运行期 Cookie，让后续快速请求复用验证结果。"""

        for item in cookies:
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
        request_observer: Callable[[], None] | None = None,
    ) -> None:
        self.cookies = cookies
        self._request_observer = request_observer
        self._manager = FetcherSession(
            impersonate=impersonate,
            # 平台适配器已经按接口合同提供 Referer 与签名头。这里关闭会自动
            # 增加 Google Referer 的通用头生成，只保留同版本浏览器 TLS 拟态。
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
        if self._request_observer is not None:
            self._request_observer()
        response = request_method(url, **kwargs)
        # FetcherSession 的 CookieJar 属于当前线程；把 Set-Cookie 合并进共享
        # CookieStore，确保同一平台其他采集线程与隐身浏览器沿用最新状态。
        curl_session = getattr(self._client, "_curl_session", None)
        jar = getattr(getattr(curl_session, "cookies", None), "jar", None)
        if jar is not None:
            self.cookies.update_from_browser(
                [
                    {
                        "name": item.name,
                        "value": item.value,
                        "domain": item.domain,
                        "path": item.path,
                        "secure": item.secure,
                        "expires": item.expires,
                    }
                    for item in jar
                ]
            )
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


class ScraplingStealthChannel:
    """为单次保护恢复启动私有 StealthySession。"""

    def __init__(
        self,
        cookies: BrowserCookieStore,
        *,
        timeout_seconds: int,
        headless: bool,
        navigation_policy: ProtectionNavigationPolicy,
    ) -> None:
        self.cookies = cookies
        self.timeout_milliseconds = max(60_000, timeout_seconds * 1000)
        self.headless = headless
        self.navigation_policy = navigation_policy
        self._manager: StealthySession | None = None
        self._client: Any = None
        self._closed = False

    def _session(self) -> Any:
        """延迟创建浏览器，普通批次全程不会支付浏览器资源成本。"""

        if self._closed:
            raise RuntimeError("Scrapling Stealthy 资源已经关闭。")
        if self._client is None:
            self._manager = StealthySession(
                headless=self.headless,
                locale="zh-CN",
                timezone_id="Asia/Shanghai",
                block_webrtc=True,
                hide_canvas=True,
                allow_webgl=True,
                disable_resources=False,
                google_search=False,
                max_pages=1,
                retries=1,
                timeout=self.timeout_milliseconds,
            )
            self._client = self._manager.__enter__()
        return self._client

    def fetch(self, url: str, *, solve_cloudflare: bool) -> ScraplingHttpResponse:
        """继承当前 Cookie，处理保护页后把新状态回灌给快速通道。"""

        session = self._session()
        context = getattr(session, "context", None)
        if context is None:
            raise RuntimeError("Scrapling Stealthy 浏览器上下文尚未建立。")
        cookies = self.cookies.browser_cookies()
        if cookies:
            context.add_cookies(cookies)
        response = session.fetch(
            url,
            solve_cloudflare=solve_cloudflare,
            google_search=False,
            disable_resources=self.navigation_policy.disable_resources,
            load_dom=self.navigation_policy.load_dom,
            network_idle=self.navigation_policy.network_idle,
            wait=max(0, self.navigation_policy.post_navigation_wait_ms),
            timeout=self.timeout_milliseconds,
        )
        self.cookies.update_from_browser(context.cookies())
        return ScraplingHttpResponse(response)

    def close(self) -> None:
        """关闭隐身浏览器；从未使用时保持零浏览器启动。"""

        if self._closed:
            return
        self._closed = True
        if self._manager is not None:
            self._manager.__exit__(None, None, None)


class ScraplingHttpPool:
    """按执行范围隔离 Cookie，并统一约束 HTTP 与浏览器资源。"""

    def __init__(
        self,
        storage_state: dict[str, Any] | None,
        *,
        timeout_seconds: int,
        impersonate: str = "chrome",
        stealth_headless: bool = True,
        scope: ExecutionScopeKey | None = None,
        browser_budget: BrowserResourceBudget | None = None,
        navigation_policy: ProtectionNavigationPolicy | None = None,
    ) -> None:
        self.cookies = BrowserCookieStore(storage_state)
        self.timeout_seconds = timeout_seconds
        self.impersonate = impersonate
        self.stealth_headless = stealth_headless
        self.scope = scope or ExecutionScopeKey()
        self.browser_budget = browser_budget or _DEFAULT_BROWSER_BUDGET
        self.navigation_policy = navigation_policy or ProtectionNavigationPolicy()
        self._thread_local = threading.local()
        self._lock = threading.Lock()
        self._stealth_lock = threading.Lock()
        self._attempt_generation = 0
        self._verified_generation = 0
        self._last_recovery: ProtectionRecoveryResult | None = None
        self._sessions: list[ScraplingHttpSession] = []
        self._http_requests = 0
        self._http_rotations = 0
        self._browser_attempts = 0
        self._browser_reuses = 0
        self._browser_usable_responses = 0
        self._browser_failures = 0
        self._confirmed_recoveries = 0
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
                request_observer=self._record_http_request,
            )
            self._thread_local.session = session
            with self._lock:
                self._sessions.append(session)
        return session

    def _record_http_request(self) -> None:
        """记录真实交给 FetcherSession 的请求次数。"""

        with self._lock:
            self._http_requests += 1

    def rotate_current_thread_session(self) -> ScraplingHttpSession:
        """关闭并替换当前线程的HTTP传输，同时保留共享Cookie状态。"""

        with self._lock:
            if self._closed:
                raise RuntimeError("Scrapling HTTP 资源池已经关闭。")
        replacement = ScraplingHttpSession(
            self.cookies,
            timeout_seconds=self.timeout_seconds,
            impersonate=self.impersonate,
            request_observer=self._record_http_request,
        )
        previous = getattr(self._thread_local, "session", None)
        with self._lock:
            if self._closed:
                replacement.close()
                raise RuntimeError("Scrapling HTTP 资源池已经关闭。")
            self._thread_local.session = replacement
            self._sessions = [item for item in self._sessions if item is not previous]
            self._sessions.append(replacement)
            self._http_rotations += 1
        if previous is not None:
            previous.close()
        return replacement

    @property
    def recovery_generation(self) -> int:
        """返回最近一次保护页导航尝试代次，供并发请求做单飞判断。"""

        with self._lock:
            return self._attempt_generation

    @property
    def cookie_generation(self) -> int:
        """兼容旧调用名；其语义是导航尝试代次，而不是已验证 Cookie。"""

        return self.recovery_generation

    @property
    def verified_recovery_generation(self) -> int:
        """返回已经由原业务请求确认解除控制的最新代次。"""

        with self._lock:
            return self._verified_generation

    def recover_protected(
        self,
        url: str,
        *,
        observed_generation: int,
        solve_cloudflare: bool = False,
    ) -> ProtectionRecoveryResult:
        """执行一次受预算约束的保护页导航，同一事件的其他线程复用结果。"""

        if self._closed:
            raise RuntimeError("Scrapling HTTP 资源池已经关闭。")
        with self._stealth_lock:
            with self._lock:
                if self._attempt_generation > observed_generation and self._last_recovery:
                    previous = self._last_recovery
                    self._browser_reuses += 1
                    return ProtectionRecoveryResult(
                        generation=previous.generation,
                        attempted=False,
                        should_retry_http=previous.should_retry_http,
                        browser_status=previous.browser_status,
                        elapsed_seconds=previous.elapsed_seconds,
                        error_type=previous.error_type,
                    )

            started = time.monotonic()
            response: ScraplingHttpResponse | None = None
            error_type: str | None = None
            stealth = ScraplingStealthChannel(
                self.cookies,
                timeout_seconds=self.timeout_seconds,
                headless=self.stealth_headless,
                navigation_policy=self.navigation_policy,
            )
            try:
                with self.browser_budget.lease(self.scope):
                    response = stealth.fetch(url, solve_cloudflare=solve_cloudflare)
            except Exception as exc:
                error_type = type(exc).__name__
                logger.warning(
                    "Scrapling Stealthy 保护页导航失败：scope=%s error=%s",
                    self.scope.platform,
                    error_type,
                )
            finally:
                try:
                    stealth.close()
                except Exception:
                    logger.warning("关闭 Scrapling Stealthy Session 失败。", exc_info=True)

            browser_status = response.status_code if response is not None else None
            should_retry_http = browser_status is not None and browser_status < 500
            elapsed = time.monotonic() - started
            with self._lock:
                self._attempt_generation += 1
                self._browser_attempts += 1
                if should_retry_http:
                    self._browser_usable_responses += 1
                else:
                    self._browser_failures += 1
                result = ProtectionRecoveryResult(
                    generation=self._attempt_generation,
                    attempted=True,
                    should_retry_http=should_retry_http,
                    browser_status=browser_status,
                    elapsed_seconds=elapsed,
                    error_type=error_type,
                )
                self._last_recovery = result
                return result

    def confirm_protected_recovery(self, generation: int) -> None:
        """由平台业务分类器确认原请求成功后，标记导航结果真实生效。"""

        with self._lock:
            if generation < 1 or generation > self._attempt_generation:
                raise ValueError("保护恢复代次不在当前资源池的有效范围内。")
            if generation > self._verified_generation:
                self._verified_generation = generation
                self._confirmed_recoveries += 1

    def stats_snapshot(self) -> ScraplingTransportSnapshot:
        """返回资源池运行统计，不包含 URL、Cookie 或账号信息。"""

        with self._lock:
            return ScraplingTransportSnapshot(
                scope=self.scope.platform,
                http_requests=self._http_requests,
                http_rotations=self._http_rotations,
                browser_attempts=self._browser_attempts,
                browser_reuses=self._browser_reuses,
                browser_usable_responses=self._browser_usable_responses,
                browser_failures=self._browser_failures,
                confirmed_recoveries=self._confirmed_recoveries,
                attempt_generation=self._attempt_generation,
                verified_generation=self._verified_generation,
            )

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
