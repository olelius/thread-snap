"""Candidate A：使用 Scrapling Spider + FetcherSession 执行纯 HTTP 批量预筛。"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import platform
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncGenerator

import scrapling
from scrapling.fetchers import FetcherSession
from scrapling.spiders import Request, Response, SessionManager, Spider

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "poc" / "shared"))

from contract import classify_document, extract_input_post_id, url_sha256, validate_result  # noqa: E402

CONTROL_CLASSES = {"rate_limited", "captcha", "challenge", "login"}
CONTROL_OR_EMPTY = CONTROL_CLASSES | {"empty"}


def utc_now() -> str:
    """返回带时区的 UTC ISO 8601 时间。"""

    return datetime.now(timezone.utc).isoformat()


def percentile(values: list[int], quantile: float) -> int:
    """按线性插值计算整数毫秒百分位。"""

    if not values:
        return 0
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    value = ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)
    return round(value)


def response_document(response: Response) -> str:
    """把 Scrapling 响应体转换为文本，不保存原始页面。"""

    return response.body.decode(getattr(response, "encoding", None) or "utf-8", errors="replace")


def error_record(url: str, started_at: str, started_perf: float, error: Exception) -> tuple[dict[str, Any], dict[str, Any]]:
    """把框架异常转换为统一结果和请求事件。"""

    duration_ms = round((time.perf_counter() - started_perf) * 1000)
    ended_at = utc_now()
    category = type(error).__name__
    result = {
        "schema_version": "1.0",
        "candidate": "candidate-a",
        "url": url,
        "url_sha256": url_sha256(url),
        "input_post_id": extract_input_post_id(url),
        "observed_post_id": None,
        "post_id_matches": False,
        "title_present": False,
        "body_present": False,
        "response_class": "error",
        "control_hit": False,
        "channel": "http",
        "status": "failed",
        "request_count": 1,
        "started_at": started_at,
        "ended_at": ended_at,
        "duration_ms": duration_ms,
        "http_status": None,
        "error_category": category,
    }
    event = {
        "schema_version": "1.0",
        "candidate": "candidate-a",
        "url": url,
        "url_sha256": url_sha256(url),
        "channel": "http",
        "started_at": started_at,
        "ended_at": ended_at,
        "duration_ms": duration_ms,
        "http_status": None,
        "final_url_sha256": None,
        "body_bytes": 0,
        "response_class": "error",
        "status": "failed",
        "error_category": category,
    }
    return result, event


class DirectHttpSpider(Spider):
    """只注册 FetcherSession 的单会话纯 HTTP Spider。"""

    name = "threadsnap-candidate-a-direct-http"
    max_blocked_retries = 0
    logging_level = logging.WARNING
    autothrottle_enabled = False

    def __init__(self, urls: list[str], concurrency: int, timeout_seconds: int) -> None:
        self.urls = urls
        self.concurrent_requests = concurrency
        self.concurrent_requests_per_domain = concurrency
        self.timeout_seconds = timeout_seconds
        self.results_by_url: dict[str, dict[str, Any]] = {}
        self.events_by_url: dict[str, dict[str, Any]] = {}
        self.completion_offsets_ms: dict[str, int] = {}
        self.run_started_perf = time.perf_counter()
        super().__init__()

    def configure_sessions(self, manager: SessionManager) -> None:
        """注册唯一 HTTP 会话，关闭框架内部重试。"""

        manager.add(
            "http",
            FetcherSession(
                impersonate="chrome",
                stealthy_headers=True,
                timeout=self.timeout_seconds,
                # Scrapling 0.4.12 的 retries=0 不执行请求；1 表示只尝试一次。
                retries=1,
                retry_delay=0,
                follow_redirects="safe",
            ),
            default=True,
        )

    async def start_requests(self) -> AsyncGenerator[Request, None]:
        """为每个 URL 生成且只生成一个直接 HTTP 请求。"""

        for url in self.urls:
            yield Request(
                url,
                sid="http",
                meta={"input_url": url, "started_at": utc_now(), "started_perf": time.perf_counter()},
            )

    async def is_blocked(self, response: Response) -> bool:
        """禁用框架重试；所有响应均交给项目统一分类器。"""

        return False

    async def parse(self, response: Response) -> AsyncGenerator[dict[str, Any] | None, None]:
        """分类一次 HTTP 响应并生成统一结果。"""

        request = response.request
        if request is None:
            raise RuntimeError("Spider 响应缺少原始请求")
        url = str(request.meta["input_url"])
        started_at = str(request.meta["started_at"])
        started_perf = float(request.meta["started_perf"])
        ended_at = utc_now()
        duration_ms = round((time.perf_counter() - started_perf) * 1000)
        document = response_document(response)
        classification = classify_document(response.url, int(response.status), document, extract_input_post_id(url))
        result = {
            "schema_version": "1.0",
            "candidate": "candidate-a",
            "url": url,
            "url_sha256": url_sha256(url),
            "input_post_id": extract_input_post_id(url),
            **classification,
            "control_hit": classification["response_class"] in CONTROL_CLASSES,
            "channel": "http",
            "request_count": 1,
            "started_at": started_at,
            "ended_at": ended_at,
            "duration_ms": duration_ms,
            "http_status": int(response.status),
            "error_category": None if classification["status"] == "success" else classification["response_class"],
        }
        event = {
            "schema_version": "1.0",
            "candidate": "candidate-a",
            "url": url,
            "url_sha256": url_sha256(url),
            "channel": "http",
            "started_at": started_at,
            "ended_at": ended_at,
            "duration_ms": duration_ms,
            "http_status": int(response.status),
            "final_url_sha256": url_sha256(response.url),
            "body_bytes": len(response.body),
            "response_class": classification["response_class"],
            "status": classification["status"],
            "error_category": result["error_category"],
        }
        self.results_by_url[url] = result
        self.events_by_url[url] = event
        self.completion_offsets_ms[url] = round((time.perf_counter() - self.run_started_perf) * 1000)
        yield result

    async def on_error(self, request: Request, error: Exception) -> None:
        """确保请求异常仍产生一条最终结果。"""

        url = str(request.meta.get("input_url", request.url))
        started_at = str(request.meta.get("started_at", utc_now()))
        started_perf = float(request.meta.get("started_perf", time.perf_counter()))
        result, event = error_record(url, started_at, started_perf, error)
        self.results_by_url[url] = result
        self.events_by_url[url] = event
        self.completion_offsets_ms[url] = round((time.perf_counter() - self.run_started_perf) * 1000)


def build_summary(
    *,
    results: list[dict[str, Any]],
    completion_offsets_ms: dict[str, int],
    duration_ms: int,
    concurrency: int,
) -> dict[str, Any]:
    """生成只基于有效结果的风控与吞吐摘要。"""

    counts = Counter(str(item["response_class"]) for item in results)
    channel_counts = Counter(str(item["channel"]) for item in results)
    success_count = sum(item["status"] == "success" for item in results)
    durations = [int(item["duration_ms"]) for item in results]
    control_results = [item for item in results if item["response_class"] in CONTROL_OR_EMPTY]
    first_control = min(control_results, key=lambda item: completion_offsets_ms[item["url"]]) if control_results else None
    total_requests = sum(int(item["request_count"]) for item in results)
    return {
        "schema_version": "1.0",
        "candidate": "candidate-a",
        "access_mode": "anonymous-direct-http",
        "direct_http_only": channel_counts == {"http": len(results)},
        "concurrency": concurrency,
        "input_count": len(results),
        "result_count": len(results),
        "success_count": success_count,
        "final_valid_rate": round(success_count / len(results), 6) if results else 0,
        "duration_ms": duration_ms,
        "processed_urls_per_second": round(len(results) / (duration_ms / 1000), 6) if duration_ms else 0,
        "effective_urls_per_second": round(success_count / (duration_ms / 1000), 6) if duration_ms else 0,
        "p50_duration_ms": percentile(durations, 0.50),
        "p95_duration_ms": percentile(durations, 0.95),
        "request_count": total_requests,
        "request_amplification": round(total_requests / len(results), 6) if results else 0,
        "channel_counts": dict(sorted(channel_counts.items())),
        "response_class_counts": dict(sorted(counts.items())),
        "first_control": None
        if first_control is None
        else {
            "url_sha256": first_control["url_sha256"],
            "response_class": first_control["response_class"],
            "completed_offset_ms": completion_offsets_ms[first_control["url"]],
        },
        "meets_2000_per_hour_speed": duration_ms > 0 and success_count / (duration_ms / 1000) >= 2000 / 3600,
        "meets_correctness_gate": len(results) > 0 and success_count == len(results),
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    """以 UTF-8/LF 写出 JSON。"""

    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    """以 UTF-8/LF 写出 JSONL。"""

    text = "".join(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n" for record in records)
    path.write_text(text, encoding="utf-8", newline="\n")


def write_checksums(output_dir: Path) -> None:
    """为本轮核心结果生成 SHA-256 清单。"""

    names = ["environment.json", "input-urls.txt", "request-events.jsonl", "summary.json", "url-results.jsonl"]
    lines = [f"{hashlib.sha256((output_dir / name).read_bytes()).hexdigest()}  {name}\n" for name in names]
    (output_dir / "SHA256SUMS").write_text("".join(lines), encoding="utf-8", newline="\n")


def parse_args() -> argparse.Namespace:
    """解析纯 HTTP 批量入口参数。"""

    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--timeout-seconds", type=int, default=30)
    args = parser.parse_args()
    if args.limit < 1 or args.concurrency < 1 or args.timeout_seconds < 1:
        parser.error("limit、concurrency 和 timeout-seconds 必须为正整数")
    return args


def main() -> int:
    """运行纯 HTTP Spider，验证统一契约并写出结果。"""

    args = parse_args()
    all_urls = [line.strip() for line in args.input.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    if args.limit > len(all_urls):
        raise ValueError("limit 超出输入清单范围")
    urls = all_urls[: args.limit]
    for url in urls:
        extract_input_post_id(url)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    (args.output_dir / "input-urls.txt").write_text("\n".join(urls) + "\n", encoding="utf-8", newline="\n")

    started_at = utc_now()
    started_perf = time.perf_counter()
    spider = DirectHttpSpider(urls, args.concurrency, args.timeout_seconds)
    spider.start()
    duration_ms = round((time.perf_counter() - started_perf) * 1000)

    missing = [url for url in urls if url not in spider.results_by_url]
    if missing:
        raise RuntimeError(f"Spider 缺少 {len(missing)} 条结果")
    results = [spider.results_by_url[url] for url in urls]
    events = [spider.events_by_url[url] for url in urls]
    contract_errors = {
        result["url_sha256"]: validate_result(result, "candidate-a")
        for result in results
        if validate_result(result, "candidate-a")
    }
    if contract_errors:
        raise RuntimeError(f"统一结果契约失败: {json.dumps(contract_errors, ensure_ascii=False)}")

    summary = build_summary(
        results=results,
        completion_offsets_ms=spider.completion_offsets_ms,
        duration_ms=duration_ms,
        concurrency=args.concurrency,
    )
    environment = {
        "schema_version": "1.0",
        "candidate": "candidate-a",
        "access_mode": "anonymous-direct-http",
        "operating_system": platform.platform(),
        "python_version": platform.python_version(),
        "python_executable": str(Path(sys.executable).resolve()),
        "scrapling_version": scrapling.__version__,
        "started_at": started_at,
        "ended_at": utc_now(),
        "input_count": len(urls),
        "input_file_sha256": hashlib.sha256((args.output_dir / "input-urls.txt").read_bytes()).hexdigest(),
        "concurrency": args.concurrency,
        "browser_started": False,
    }
    write_jsonl(args.output_dir / "url-results.jsonl", results)
    write_jsonl(args.output_dir / "request-events.jsonl", events)
    write_json(args.output_dir / "summary.json", summary)
    write_json(args.output_dir / "environment.json", environment)
    write_checksums(args.output_dir)
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
