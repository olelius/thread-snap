"""候选 A：使用 Scrapling 持久认证会话执行定量吞吐测试。"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import scrapling
from scrapling.fetchers import AsyncDynamicSession

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "poc" / "shared"))

from contract import classify_document, extract_input_post_id, url_sha256  # noqa: E402

CONTROL_CLASSES = {"rate_limited", "captcha", "challenge", "login"}


def utc_now() -> str:
    """返回带时区的 UTC ISO 8601 时间。"""

    return datetime.now(timezone.utc).isoformat()


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


async def verify_login(session: AsyncDynamicSession, url: str, account: str, password: str, wait_ms: int) -> dict[str, Any]:
    """在同一持久浏览器上下文建立或确认登录会话。"""

    state = {"submitted": False, "verification_required": False}

    async def page_action(page: Any) -> None:
        await page.wait_for_timeout(2_000)
        if "/login-required" in page.url:
            if await page.locator('input[name="code"]').count():
                await page.locator("button").last.click(timeout=5_000)
                await page.wait_for_timeout(500)
            await page.locator('input[name="account"]').fill(account)
            await page.locator('input[name="password"]').fill(password)
            await page.get_by_role("button", name="登录", exact=True).click(timeout=10_000)
            state["submitted"] = True
            await page.wait_for_timeout(10_000)
        document = await page.content()
        state["verification_required"] = any(marker in document.lower() for marker in ("captcha", "验证码", "验证中心"))

    response = await session.fetch(
        url,
        google_search=False,
        page_action=page_action,
        wait=wait_ms,
        timeout=90_000,
        network_idle=False,
    )
    document = response_document(response)
    final_url = str(response.url)
    classification = classify_document(final_url, int(response.status), document, extract_input_post_id(url))
    logged_in = classification["status"] == "success" and not state["verification_required"]
    return {
        "schema_version": "1.0",
        "candidate": "candidate-a",
        "submitted": state["submitted"],
        "logged_in": logged_in,
        "verification_required": state["verification_required"],
        "response_class": classification["response_class"],
        "status": classification["status"],
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
        real_chrome=bool(candidate_config.get("real_chrome", False)),
    ) as session:
        login_result = await verify_login(session, urls[0], str(config["account"]), str(config["password"]), wait_ms)
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
    return asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
