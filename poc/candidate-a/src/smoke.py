"""候选 A：Scrapling HTTP 优先、动态页面回退的阶段 1 冒烟。"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from scrapling.fetchers import DynamicFetcher, Fetcher
import scrapling

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "poc" / "shared"))

from contract import classify_document, extract_input_post_id, url_sha256  # noqa: E402

CONTROL_CLASSES = {"rate_limited", "captcha", "challenge", "login"}


def utc_now() -> str:
    """返回带时区的 UTC ISO 8601 时间。"""

    return datetime.now(timezone.utc).isoformat()


def response_document(response: Any) -> str:
    """把 Scrapling 响应体统一转换为 UTF-8 文本。"""

    body = response.body
    if isinstance(body, bytes):
        return body.decode(getattr(response, "encoding", None) or "utf-8", errors="replace")
    return str(body)


def fetch_http(url: str) -> tuple[str, int | None, str]:
    """使用 Scrapling 普通 HTTP 通道访问单个 URL。"""

    response = Fetcher.get(url, timeout=30, retries=1)
    return str(getattr(response, "url", url)), int(response.status), response_document(response)


def fetch_dynamic(url: str) -> tuple[str, int | None, str]:
    """使用 Scrapling 标准动态页面通道访问单个 URL。"""

    response = DynamicFetcher.fetch(
        url,
        headless=True,
        wait=5,
        timeout=45_000,
        network_idle=False,
        retries=1,
    )
    return str(getattr(response, "url", url)), int(response.status), response_document(response)


def run_attempt(
    *,
    candidate: str,
    url: str,
    input_post_id: str,
    channel: str,
    fetcher: Callable[[str], tuple[str, int | None, str]],
    capture_path: Path,
) -> dict[str, Any]:
    """执行一次通道访问并返回统一请求事件。"""

    started_at = utc_now()
    started = time.perf_counter()
    try:
        final_url, http_status, document = fetcher(url)
        capture_path.parent.mkdir(parents=True, exist_ok=True)
        capture_path.write_text(document, encoding="utf-8")
        classification = classify_document(final_url, http_status, document, input_post_id)
        error_category = None if classification["status"] == "success" else classification["response_class"]
        return {
            "schema_version": "1.0",
            "candidate": candidate,
            "url": url,
            "url_sha256": url_sha256(url),
            "channel": channel,
            "started_at": started_at,
            "ended_at": utc_now(),
            "duration_ms": round((time.perf_counter() - started) * 1000),
            "http_status": http_status,
            "final_url_sha256": url_sha256(final_url),
            **classification,
            "error_category": error_category,
        }
    except Exception as exc:  # 框架异常必须形成逐 URL 证据，不能中断后静默丢失。
        return {
            "schema_version": "1.0",
            "candidate": candidate,
            "url": url,
            "url_sha256": url_sha256(url),
            "channel": channel,
            "started_at": started_at,
            "ended_at": utc_now(),
            "duration_ms": round((time.perf_counter() - started) * 1000),
            "http_status": None,
            "final_url_sha256": None,
            "observed_post_id": None,
            "post_id_matches": False,
            "title_present": False,
            "body_present": False,
            "response_class": "error",
            "status": "failed",
            "error_category": type(exc).__name__,
        }


def build_result(url: str, output_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """先 HTTP 后动态回退，形成一条最终结果和完整请求事件。"""

    candidate = "candidate-a"
    input_post_id = extract_input_post_id(url)
    url_id = url_sha256(url)
    started_at = utc_now()
    started = time.perf_counter()
    attempts = [
        run_attempt(
            candidate=candidate,
            url=url,
            input_post_id=input_post_id,
            channel="http",
            fetcher=fetch_http,
            capture_path=output_dir / "captures" / f"{url_id}-http.html",
        )
    ]
    if attempts[-1]["status"] != "success":
        attempts.append(
            run_attempt(
                candidate=candidate,
                url=url,
                input_post_id=input_post_id,
                channel="browser-dom",
                fetcher=fetch_dynamic,
                capture_path=output_dir / "captures" / f"{url_id}-browser.html",
            )
        )
    final = attempts[-1]
    result = {
        "schema_version": "1.0",
        "candidate": candidate,
        "url": url,
        "url_sha256": url_id,
        "input_post_id": input_post_id,
        "observed_post_id": final["observed_post_id"],
        "post_id_matches": final["post_id_matches"],
        "title_present": final["title_present"],
        "body_present": final["body_present"],
        "response_class": final["response_class"],
        "control_hit": any(attempt["response_class"] in CONTROL_CLASSES for attempt in attempts),
        "channel": final["channel"],
        "status": final["status"],
        "request_count": len(attempts),
        "started_at": started_at,
        "ended_at": utc_now(),
        "duration_ms": round((time.perf_counter() - started) * 1000),
        "http_status": final["http_status"],
        "error_category": final["error_category"],
    }
    return result, attempts


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    """以 UTF-8/LF 写出 JSONL。"""

    payload = "".join(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n" for record in records)
    path.write_bytes(payload.encode("utf-8"))


def write_environment(path: Path, input_path: Path, input_count: int) -> None:
    """记录阶段 1 冒烟的最小可复现环境，不采集凭证或无关机器文件。"""

    payload = {
        "schema_version": "1.0",
        "candidate": "candidate-a",
        "access_mode": "anonymous",
        "operating_system": platform.platform(),
        "python_version": platform.python_version(),
        "python_executable": str(Path(sys.executable).resolve()),
        "scrapling_version": scrapling.__version__,
        "input_count": input_count,
        "input_file_sha256": hashlib.sha256(input_path.read_bytes()).hexdigest(),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=3)
    args = parser.parse_args()

    urls = [line.strip() for line in args.input.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    if args.limit < 1 or args.limit > len(urls):
        raise ValueError("limit 超出输入清单范围")
    urls = urls[: args.limit]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    for url in urls:
        result, attempts = build_result(url, args.output_dir)
        results.append(result)
        events.extend(attempts)
        print(
            json.dumps(
                {
                    "url_sha256": result["url_sha256"],
                    "status": result["status"],
                    "response_class": result["response_class"],
                    "channel": result["channel"],
                },
                ensure_ascii=False,
            )
        )
    write_jsonl(args.output_dir / "url-results.jsonl", results)
    write_jsonl(args.output_dir / "request-events.jsonl", events)
    write_environment(args.output_dir / "environment.json", args.input, len(urls))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
