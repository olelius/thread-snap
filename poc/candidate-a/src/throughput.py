"""候选 A：使用 Scrapling 持久认证会话执行定量吞吐测试。"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

import scrapling
from scrapling.fetchers import AsyncDynamicSession

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "poc" / "shared"))

from contract import classify_document, extract_input_post_id, url_sha256  # noqa: E402

CONTROL_CLASSES = {"rate_limited", "captcha", "challenge", "login"}
SECONDARY_SMS_MARKER = "为保证账号安全，请使用手机验证码登录"
LOGIN_REASON_MARKERS = (
    SECONDARY_SMS_MARKER,
    "短信验证码",
    "获取验证码",
    "发送验证码",
    "手机验证",
    "手机号验证",
    "验证码",
    "验证中心",
    "安全验证",
    "滑动验证",
    "向右滑动",
    "账号或密码错误",
    "账号不存在",
    "密码错误",
    "登录失败",
    "操作频繁",
    "请稍后重试",
)
VERIFICATION_REASON_MARKERS = frozenset(LOGIN_REASON_MARKERS[:11])
LOGIN_BLOCKED_RESOURCE_TYPES = frozenset(
    {"font", "image", "media", "beacon", "object", "imageset", "texttrack", "websocket", "csp_report"}
)
SMS_CODE_PATTERN = re.compile(r"^[0-9]{4,8}$")


def utc_now() -> str:
    """返回带时区的 UTC ISO 8601 时间。"""

    return datetime.now(timezone.utc).isoformat()


def read_sms_code(candidate: str) -> str:
    """从当前终端读取一次性短信码，不把值写入配置或结果。"""

    prompt = f"[{candidate}] 请输入手机收到的 4-8 位验证码: "
    if sys.stdin.isatty():
        code = input(prompt)
    else:
        code = sys.stdin.readline()
    code = code.strip()
    if not SMS_CODE_PATTERN.fullmatch(code):
        raise ValueError("短信验证码必须是 4-8 位数字")
    return code


async def setup_login_resource_routing(page: Any) -> None:
    """保留样式与脚本，仅丢弃可能拖住登录页面 load 的非必要资源。"""

    async def route_handler(route: Any) -> None:
        if route.request.resource_type in LOGIN_BLOCKED_RESOURCE_TYPES:
            await route.abort()
        else:
            await route.continue_()

    await page.route("**/*", route_handler)


async def first_visible(page: Any, selector: str, timeout_ms: int = 10_000) -> Any:
    """返回组合选择器中的第一个可见控件。"""

    locator = page.locator(selector)
    await locator.first.wait_for(state="attached", timeout=timeout_ms)
    for index in range(min(await locator.count(), 20)):
        item = locator.nth(index)
        if await item.is_visible():
            return item
    raise RuntimeError("未找到可见登录控件")


async def click_first_visible_text(page: Any, labels: tuple[str, ...]) -> str:
    """按给定顺序点击第一个可见的精确文本控件。"""

    for label in labels:
        options = page.get_by_text(label, exact=True)
        for index in range(min(await options.count(), 10)):
            option = options.nth(index)
            if await option.is_visible():
                await option.click(timeout=10_000)
                return label
    raise RuntimeError("未找到可见登录操作")


def response_document(response: Any) -> str:
    """把 Scrapling 响应体统一转换为文本。"""

    body = response.body
    if isinstance(body, bytes):
        return body.decode(getattr(response, "encoding", None) or "utf-8", errors="replace")
    return str(body)


def load_config(path: Path) -> dict[str, Any]:
    """读取并校验 Linux 测试配置，路径均相对配置文件解析。"""

    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("配置根节点必须是对象")
    required = {"account", "password", "input_file", "expected_count", "window_seconds", "candidate_a"}
    missing = sorted(required - value.keys())
    if missing:
        raise ValueError(f"配置缺少字段: {', '.join(missing)}")
    if not isinstance(value["account"], str) or not value["account"]:
        raise ValueError("account 必须是非空字符串")
    if not isinstance(value["password"], str) or not value["password"]:
        raise ValueError("password 必须是非空字符串")
    for name in ("expected_count", "window_seconds"):
        if not isinstance(value[name], int) or isinstance(value[name], bool) or value[name] < 1:
            raise ValueError(f"{name} 必须是正整数")
    candidate = value["candidate_a"]
    if not isinstance(candidate, dict):
        raise ValueError("candidate_a 必须是对象")
    concurrency = candidate.get("concurrency", 8)
    if not isinstance(concurrency, int) or isinstance(concurrency, bool) or not 1 <= concurrency <= 64:
        raise ValueError("candidate_a.concurrency 必须在 1..64")
    return value


def load_urls(config_path: Path, config: dict[str, Any]) -> tuple[Path, list[str]]:
    """读取约定数量的不重复 URL。"""

    input_path = (config_path.parent / str(config["input_file"])).resolve()
    urls = [line.strip() for line in input_path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    expected = int(config["expected_count"])
    if len(urls) < expected:
        raise ValueError(f"输入只有 {len(urls)} 条，少于 expected_count={expected}")
    urls = urls[:expected]
    if len(set(urls)) != len(urls):
        raise ValueError("测试范围内含重复 URL")
    for url in urls:
        extract_input_post_id(url)
    return input_path, urls


def load_completed(path: Path) -> set[str]:
    """读取已落盘结果，用于中断后只补齐未完成 URL。"""

    if not path.exists():
        return set()
    completed: set[str] = set()
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        record = json.loads(line)
        url = record.get("url")
        if not isinstance(url, str):
            raise ValueError(f"已有结果第 {line_no} 行缺少 URL")
        if url in completed:
            raise ValueError(f"已有结果第 {line_no} 行 URL 重复")
        completed.add(url)
    return completed


def load_profile_cookies(profile_dir: Path) -> list[dict[str, Any]] | None:
    """读取短信初始化保存的浏览器状态；值只进入候选进程内存。"""

    state_path = profile_dir / "storage-state.json"
    if not state_path.is_file():
        return None
    value = json.loads(state_path.read_text(encoding="utf-8"))
    cookies = value.get("cookies") if isinstance(value, dict) else None
    if not isinstance(cookies, list):
        raise ValueError("候选 A storage-state.json 缺少 cookies")
    return cookies


def failed_result(
    url: str,
    started_at: str,
    started: float,
    request_count: int,
    category: str,
    *,
    response_class: str = "error",
    status: str = "failed",
    control_hit: bool = False,
) -> dict[str, Any]:
    """生成真实失败或截止时间未启动的统一结果。"""

    return {
        "schema_version": "1.0",
        "candidate": "candidate-a",
        "url": url,
        "url_sha256": url_sha256(url),
        "input_post_id": extract_input_post_id(url),
        "observed_post_id": None,
        "post_id_matches": False,
        "title_present": False,
        "body_present": False,
        "response_class": response_class,
        "control_hit": control_hit,
        "channel": "browser-dom",
        "status": status,
        "request_count": request_count,
        "started_at": started_at,
        "ended_at": utc_now(),
        "duration_ms": round((time.perf_counter() - started) * 1000),
        "http_status": None,
        "error_category": category,
    }


async def any_visible(page: Any, selector: str) -> bool:
    """判断至多前十个匹配节点中是否存在可见节点。"""

    locator = page.locator(selector)
    for index in range(min(await locator.count(), 10)):
        if await locator.nth(index).is_visible():
            return True
    return False


async def collect_login_diagnostic(
    page: Any,
    account: str,
    password: str,
    output_dir: Path,
    capture_screenshot: bool,
) -> dict[str, Any]:
    """记录不含完整 URL、HTML、Cookie 或凭证的登录后可见状态。"""

    try:
        body_text = await page.locator("body").inner_text(timeout=5_000)
    except Exception:  # noqa: BLE001
        body_text = ""
    marker_hits = [marker for marker in LOGIN_REASON_MARKERS if marker in body_text]
    selector_map = {
        "sms_code_input": 'input[name="code"], input[placeholder*="验证码"]',
        "captcha_frame": 'iframe[src*="captcha" i]',
        "captcha_container": '[class*="captcha" i], [id*="captcha" i]',
        "verification_container": '[class*="verify" i], [id*="verify" i]',
        "slider_container": '[class*="slide" i], [class*="slider" i]',
        "account_input": 'input[name="account"]',
        "password_input": 'input[name="password"]',
    }
    visible_selectors: dict[str, bool] = {}
    for name, selector in selector_map.items():
        try:
            visible_selectors[name] = await any_visible(page, selector)
        except Exception:  # noqa: BLE001
            visible_selectors[name] = False

    parsed = urlsplit(str(page.url))
    secrets = [value for value in (account, password, account[:3], account[-4:]) if value]
    try:
        page_title = str(await page.title())[:120]
    except Exception:  # noqa: BLE001
        page_title = ""
    for secret in secrets:
        page_title = page_title.replace(secret, "[REDACTED]")
    verification_selectors = (
        visible_selectors["sms_code_input"],
        visible_selectors["captcha_frame"],
        visible_selectors["captcha_container"],
        visible_selectors["verification_container"],
        visible_selectors["slider_container"],
    )
    diagnostic: dict[str, Any] = {
        "schema_version": "1.0",
        "candidate": "candidate-a",
        "final_path": parsed.path,
        "query_keys": sorted({name for name, _ in parse_qsl(parsed.query, keep_blank_values=True)}),
        "page_title": page_title,
        "reason_markers": marker_hits,
        "secondary_sms_required": SECONDARY_SMS_MARKER in body_text,
        "visible_selectors": visible_selectors,
        "verification_visible": any(marker in VERIFICATION_REASON_MARKERS for marker in marker_hits)
        or any(verification_selectors),
        "screenshot": None,
        "screenshot_error": None,
    }
    if capture_screenshot and ("/login" in parsed.path or diagnostic["verification_visible"]):
        try:
            await page.evaluate(
                """({ secrets }) => {
                    document.querySelectorAll('input, textarea').forEach((element) => {
                        element.value = '';
                        element.setAttribute('value', '');
                    });
                    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
                        for (const secret of secrets) {
                            if (secret) node.textContent = (node.textContent || '').split(secret).join('[REDACTED]');
                        }
                    }
                }""",
                {"secrets": secrets},
            )
            screenshot_name = "login-page-redacted.png"
            await page.screenshot(path=str(output_dir / screenshot_name), full_page=True)
            diagnostic["screenshot"] = screenshot_name
        except Exception as error:  # noqa: BLE001
            diagnostic["screenshot_error"] = type(error).__name__
    return diagnostic


async def verify_login(
    session: AsyncDynamicSession,
    url: str,
    account: str,
    password: str,
    wait_ms: int,
    output_dir: Path,
    capture_diagnostic: bool,
) -> dict[str, Any]:
    """在同一持久浏览器上下文建立或确认登录会话。"""

    state: dict[str, Any] = {"submitted": False, "password_login_selected": False, "diagnostic": None}

    async def page_setup(page: Any) -> None:
        async def route_handler(route: Any) -> None:
            if route.request.resource_type in LOGIN_BLOCKED_RESOURCE_TYPES:
                await route.abort()
            else:
                await route.continue_()

        await page.route("**/*", route_handler)

    async def page_action(page: Any) -> None:
        await page.wait_for_timeout(2_000)
        if "/login-required" in page.url:
            password_options = page.get_by_text("密码登录", exact=True)
            for index in range(min(await password_options.count(), 10)):
                option = password_options.nth(index)
                if await option.is_visible():
                    await option.click(timeout=5_000)
                    state["password_login_selected"] = True
                    await page.wait_for_timeout(500)
                    break
            account_input = page.locator('input[name="account"]')
            password_input = page.locator('input[name="password"]')
            await account_input.wait_for(state="visible", timeout=10_000)
            await password_input.wait_for(state="visible", timeout=10_000)
            await account_input.fill(account)
            await password_input.fill(password)
            await page.get_by_role("button", name="登录", exact=True).click(timeout=10_000)
            state["submitted"] = True
            await page.wait_for_timeout(10_000)
        try:
            state["diagnostic"] = await collect_login_diagnostic(
                page,
                account,
                password,
                output_dir,
                capture_diagnostic,
            )
        except Exception as error:  # noqa: BLE001
            state["diagnostic"] = {
                "schema_version": "1.0",
                "candidate": "candidate-a",
                "verification_visible": False,
                "screenshot": None,
                "screenshot_error": type(error).__name__,
            }

    response = await session.fetch(
        url,
        google_search=False,
        page_setup=page_setup,
        page_action=page_action,
        wait=wait_ms,
        timeout=90_000,
        network_idle=False,
    )
    document = response_document(response)
    final_url = str(response.url)
    classification = classify_document(final_url, int(response.status), document, extract_input_post_id(url))
    diagnostic = state["diagnostic"] or {
        "schema_version": "1.0",
        "candidate": "candidate-a",
        "verification_visible": False,
        "screenshot": None,
        "screenshot_error": "diagnostic_not_collected",
    }
    if capture_diagnostic:
        (output_dir / "login-diagnostic.json").write_text(
            json.dumps(diagnostic, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    verification_required = bool(diagnostic.get("verification_visible"))
    logged_in = classification["status"] == "success" and not verification_required
    return {
        "schema_version": "1.0",
        "candidate": "candidate-a",
        "submitted": state["submitted"],
        "password_login_selected": state["password_login_selected"],
        "logged_in": logged_in,
        "verification_required": verification_required,
        "response_class": classification["response_class"],
        "status": classification["status"],
        "diagnostic_file": "login-diagnostic.json" if capture_diagnostic else None,
    }


async def bootstrap_sms_session(
    session: AsyncDynamicSession,
    url: str,
    account: str,
    profile_dir: Path,
) -> dict[str, Any]:
    """在当前 SSH 终端读取一次短信码，并写入候选 A 的持久浏览器配置。"""

    state: dict[str, Any] = {
        "sms_requested": False,
        "submitted": False,
        "classification": None,
        "error_category": None,
    }

    async def page_action(page: Any) -> None:
        try:
            if "/login-required" in page.url:
                for label in ("验证码登录", "手机验证码登录"):
                    options = page.get_by_text(label, exact=True)
                    clicked = False
                    for index in range(min(await options.count(), 10)):
                        option = options.nth(index)
                        if await option.is_visible():
                            await option.click(timeout=10_000)
                            await page.wait_for_timeout(500)
                            clicked = True
                            break
                    if clicked:
                        break

                account_input = await first_visible(
                    page,
                    'input[name="account"], input[placeholder*="手机号"]',
                )
                code_input = await first_visible(
                    page,
                    'input[name="code"], input[placeholder*="验证码"]',
                )
                await account_input.evaluate("element => element.setAttribute('autocomplete', 'off')")
                await code_input.evaluate("element => element.setAttribute('autocomplete', 'off')")
                await code_input.evaluate("element => element.form?.setAttribute('autocomplete', 'off')")
                await account_input.fill(account)
                await click_first_visible_text(page, ("获取验证码", "发送验证码"))
                state["sms_requested"] = True
                code = await asyncio.to_thread(read_sms_code, "candidate-a")
                await code_input.fill(code)
                code = ""
                await click_first_visible_text(page, ("登录/注册", "登录"))
                state["submitted"] = True
                await page.wait_for_timeout(10_000)

            html_document = await page.content()
            state["classification"] = classify_document(
                page.url,
                200,
                html_document,
                extract_input_post_id(url),
            )
            if state["classification"]["status"] == "success":
                state_path = profile_dir / "storage-state.json"
                await page.context.storage_state(path=str(state_path))
                state_path.chmod(0o600)
        except Exception as error:  # noqa: BLE001
            state["error_category"] = type(error).__name__

    try:
        await session.fetch(
            url,
            google_search=False,
            page_setup=setup_login_resource_routing,
            page_action=page_action,
            wait=500,
            timeout=600_000,
            network_idle=False,
        )
    except Exception as error:  # noqa: BLE001
        state["error_category"] = state["error_category"] or type(error).__name__

    classification = state["classification"] or {
        "response_class": "error",
        "status": "failed",
    }
    return {
        "schema_version": "1.0",
        "candidate": "candidate-a",
        "mode": "interactive_sms_bootstrap",
        "sms_requested": state["sms_requested"],
        "submitted": state["submitted"],
        "logged_in": classification["status"] == "success",
        "response_class": classification["response_class"],
        "status": classification["status"],
        "error_category": state["error_category"],
    }


async def main_async(args: argparse.Namespace) -> int:
    """执行登录、并发抓取、即时落盘和截止时间收口。"""

    config_path = args.config.resolve()
    config = load_config(config_path)
    input_path, urls = load_urls(config_path, config)
    candidate_config = config["candidate_a"]
    concurrency = int(candidate_config.get("concurrency", 8))
    max_attempts = int(config.get("max_attempts", 2))
    wait_ms = int(config.get("wait_ms", 1_000))
    retry_delay_ms = int(config.get("retry_delay_ms", 1_500))
    request_timeout_ms = int(config.get("request_timeout_ms", 45_000))
    if not 1 <= max_attempts <= 5:
        raise ValueError("max_attempts 必须在 1..5")

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    results_path = output_dir / "url-results.jsonl"
    events_path = output_dir / "request-events.jsonl"
    completed = load_completed(results_path)
    unknown = completed - set(urls)
    if unknown:
        raise ValueError("已有结果包含本轮清单外 URL")
    pending = [url for url in urls if url not in completed]
    profile_dir = (config_path.parent / str(candidate_config.get("profile_dir", "profiles/candidate-a"))).resolve()
    profile_dir.mkdir(parents=True, exist_ok=True)
    if args.bootstrap_sms:
        async with AsyncDynamicSession(
            headless=bool(config.get("headless", True)),
            google_search=False,
            max_pages=1,
            timeout=600_000,
            retries=1,
            user_data_dir=str(profile_dir),
            cookies=load_profile_cookies(profile_dir),
            real_chrome=bool(candidate_config.get("real_chrome", False)),
        ) as session:
            result = await bootstrap_sms_session(session, urls[0], str(config["account"]), profile_dir)
        (output_dir / "sms-bootstrap-result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return 0 if result["logged_in"] else 5

    write_lock = asyncio.Lock()
    deadline = time.monotonic() + int(config["window_seconds"])
    environment = {
        "schema_version": "1.0",
        "candidate": "candidate-a",
        "access_mode": "authenticated",
        "python_version": sys.version.split()[0],
        "scrapling_version": scrapling.__version__,
        "input_file": str(input_path),
        "expected_count": len(urls),
        "concurrency": concurrency,
        "window_seconds": int(config["window_seconds"]),
    }
    (output_dir / "runner-environment.json").write_text(
        json.dumps(environment, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    async def append_jsonl(path: Path, record: dict[str, Any]) -> None:
        payload = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
        async with write_lock:
            with path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
                handle.flush()

    async with AsyncDynamicSession(
        headless=bool(config.get("headless", True)),
        google_search=False,
        max_pages=concurrency,
        timeout=request_timeout_ms,
        retries=1,
        user_data_dir=str(profile_dir),
        cookies=load_profile_cookies(profile_dir),
        real_chrome=bool(candidate_config.get("real_chrome", False)),
    ) as session:
        login_result = await verify_login(
            session,
            urls[0],
            str(config["account"]),
            str(config["password"]),
            wait_ms,
            output_dir,
            bool(config.get("capture_login_diagnostic", False)),
        )
        (output_dir / "login-result.json").write_text(
            json.dumps(login_result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        if not login_result["logged_in"]:
            response_class = str(login_result["response_class"])
            is_control = response_class in CONTROL_CLASSES
            for url in pending:
                started_at = utc_now()
                started = time.perf_counter()
                await append_jsonl(
                    results_path,
                    failed_result(
                        url,
                        started_at,
                        started,
                        0,
                        "login_initialization_failed",
                        response_class=response_class if is_control else "error",
                        status="blocked" if is_control else "failed",
                        control_hit=is_control,
                    ),
                )
            return 4

        queue: asyncio.Queue[str] = asyncio.Queue()
        for url in pending:
            queue.put_nowait(url)

        async def process_url(url: str) -> None:
            started_at = utc_now()
            started = time.perf_counter()
            attempts: list[dict[str, Any]] = []
            final: dict[str, Any] | None = None
            for attempt in range(1, max_attempts + 1):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                attempt_started_at = utc_now()
                attempt_started = time.perf_counter()
                try:
                    async with asyncio.timeout(min(remaining, request_timeout_ms / 1000)):
                        response = await session.fetch(
                            url,
                            google_search=False,
                            wait=wait_ms,
                            timeout=min(request_timeout_ms, max(1_000, int(remaining * 1000))),
                            network_idle=False,
                            disable_resources=True,
                        )
                    document = response_document(response)
                    final_url = str(response.url)
                    http_status = int(response.status)
                    classification = classify_document(final_url, http_status, document, extract_input_post_id(url))
                    event = {
                        "schema_version": "1.0",
                        "candidate": "candidate-a",
                        "url": url,
                        "url_sha256": url_sha256(url),
                        "attempt": attempt,
                        "channel": "browser-dom",
                        "started_at": attempt_started_at,
                        "ended_at": utc_now(),
                        "duration_ms": round((time.perf_counter() - attempt_started) * 1000),
                        "http_status": http_status,
                        "final_url_sha256": url_sha256(final_url),
                        **classification,
                        "error_category": None if classification["status"] == "success" else classification["response_class"],
                    }
                except TimeoutError:
                    event = {
                        "schema_version": "1.0", "candidate": "candidate-a", "url": url,
                        "url_sha256": url_sha256(url), "attempt": attempt, "channel": "browser-dom",
                        "started_at": attempt_started_at, "ended_at": utc_now(),
                        "duration_ms": round((time.perf_counter() - attempt_started) * 1000),
                        "http_status": None, "final_url_sha256": None, "observed_post_id": None,
                        "post_id_matches": False, "title_present": False, "body_present": False,
                        "response_class": "error", "status": "failed", "error_category": "network_timeout",
                    }
                except Exception as exc:  # 每次框架错误均形成证据，具体消息不写入以免带出页面数据。
                    event = {
                        "schema_version": "1.0", "candidate": "candidate-a", "url": url,
                        "url_sha256": url_sha256(url), "attempt": attempt, "channel": "browser-dom",
                        "started_at": attempt_started_at, "ended_at": utc_now(),
                        "duration_ms": round((time.perf_counter() - attempt_started) * 1000),
                        "http_status": None, "final_url_sha256": None, "observed_post_id": None,
                        "post_id_matches": False, "title_present": False, "body_present": False,
                        "response_class": "error", "status": "failed", "error_category": type(exc).__name__,
                    }
                attempts.append(event)
                await append_jsonl(events_path, event)
                if event["status"] == "success":
                    final = event
                    break
                if (
                    event["http_status"] is not None
                    and 400 <= event["http_status"] < 500
                    and event["http_status"] != 429
                    and event["response_class"] not in CONTROL_CLASSES
                ):
                    break
                if attempt < max_attempts and time.monotonic() < deadline:
                    await asyncio.sleep(retry_delay_ms / 1000)

            if attempts:
                last = final or attempts[-1]
                result = {
                    "schema_version": "1.0", "candidate": "candidate-a", "url": url,
                    "url_sha256": url_sha256(url), "input_post_id": extract_input_post_id(url),
                    "observed_post_id": last["observed_post_id"], "post_id_matches": last["post_id_matches"],
                    "title_present": last["title_present"], "body_present": last["body_present"],
                    "response_class": last["response_class"],
                    "control_hit": any(item["response_class"] in CONTROL_CLASSES for item in attempts),
                    "channel": "browser-dom", "status": last["status"], "request_count": len(attempts),
                    "started_at": started_at, "ended_at": utc_now(),
                    "duration_ms": round((time.perf_counter() - started) * 1000),
                    "http_status": last["http_status"], "error_category": last["error_category"],
                }
            else:
                result = failed_result(url, started_at, started, 0, "deadline_not_started")
            await append_jsonl(results_path, result)
            print(json.dumps({"url_sha256": result["url_sha256"], "status": result["status"]}, ensure_ascii=False), flush=True)

        async def worker() -> None:
            while True:
                try:
                    url = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                try:
                    await process_url(url)
                finally:
                    queue.task_done()

        await asyncio.gather(*(worker() for _ in range(concurrency)))

    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--bootstrap-sms", action="store_true")
    return asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
