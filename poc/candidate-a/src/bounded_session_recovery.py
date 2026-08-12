"""Candidate A：在认证 HTTP 首控后有界重建 Scrapling Session 并继续队列。"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import platform
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Callable

import scrapling
from scrapling.fetchers import AsyncDynamicSession
from scrapling.spiders.result import ItemList

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "poc" / "shared"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from contract import extract_input_post_id, validate_result  # noqa: E402
from http_throughput import DirectHttpSpider, utc_now, write_json, write_jsonl  # noqa: E402
from session_handoff import load_http_cookies  # noqa: E402
from session_profile import prepare_isolated_profile  # noqa: E402
from throughput import load_config, verify_login  # noqa: E402

RECOVERABLE_SESSION_CLASSES = frozenset({"empty", "login", "session_state_unusable"})
NON_RECOVERABLE_CONTROL_CLASSES = frozenset({"captcha", "challenge", "rate_limited"})


def parse_args() -> argparse.Namespace:
    """解析有界 Session 恢复入口。"""

    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--gate-input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--initial-storage-state", type=Path)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=2000)
    parser.add_argument("--max-recoveries", type=int, default=2)
    parser.add_argument("--timeout-seconds", type=int, default=30)
    parser.add_argument("--window-seconds", type=int, default=3600)
    args = parser.parse_args()
    if args.offset < 0:
        parser.error("offset 不能为负数")
    if not 1 <= args.limit <= 2000:
        parser.error("limit 必须在 1..2000")
    if not 0 <= args.max_recoveries <= 5:
        parser.error("max-recoveries 必须在 0..5")
    if args.timeout_seconds < 1 or args.window_seconds < 1:
        parser.error("timeout-seconds 和 window-seconds 必须为正整数")
    return args


def load_selected_urls(path: Path, offset: int, limit: int) -> tuple[list[str], str]:
    """读取固定清单片段并验证同域、不重复与帖子身份。"""

    all_urls = [line.strip() for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    if offset + limit > len(all_urls):
        raise ValueError("offset + limit 超出输入清单范围")
    urls = all_urls[offset : offset + limit]
    if len(set(urls)) != len(urls):
        raise ValueError("恢复范围内含重复 URL")
    for url in urls:
        extract_input_post_id(url)
    hosts = {(url.split("/", 3)[2]).lower() for url in urls}
    if len(hosts) != 1:
        raise ValueError("恢复入口只接受同一主机的样本")
    return urls, hashlib.sha256(path.read_bytes()).hexdigest()


def load_gate_urls(path: Path) -> list[str]:
    """读取固定三条门禁样本。"""

    urls = [line.strip() for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    if len(urls) != 3 or len(set(urls)) != 3:
        raise ValueError("gate-input 必须包含3条不同 URL")
    for url in urls:
        extract_input_post_id(url)
    return urls


def run_http_segment(
    urls: list[str],
    storage_state: Path,
    timeout_seconds: int,
    session_ordinal: int,
    segment_kind: str,
) -> dict[str, Any]:
    """使用 Scrapling Spider 和 FetcherSession 执行一个首控暂停段。"""

    cookies, cookie_metadata = load_http_cookies(storage_state, urls[0])
    spider = DirectHttpSpider(
        urls,
        concurrency=1,
        timeout_seconds=timeout_seconds,
        request_cookies=cookies,
        pause_on_control=True,
    )
    started = time.perf_counter()
    crawl_result = spider.start()
    duration_ms = round((time.perf_counter() - started) * 1000)
    completed_urls = [url for url in urls if url in spider.results_by_url]
    stopped_by_policy = bool(crawl_result.paused or spider.pause_reason)
    if len(completed_urls) != len(urls) and not stopped_by_policy:
        raise RuntimeError(f"Spider 缺少 {len(urls) - len(completed_urls)} 条结果")

    results: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    for url in completed_urls:
        result = dict(spider.results_by_url[url])
        event = dict(spider.events_by_url[url])
        result.update({"session_ordinal": session_ordinal, "segment_kind": segment_kind})
        event.update({"session_ordinal": session_ordinal, "segment_kind": segment_kind})
        errors = validate_result(result, "candidate-a")
        if errors:
            raise RuntimeError(f"统一结果契约失败: {json.dumps(errors, ensure_ascii=False)}")
        results.append(result)
        events.append(event)
    return {
        "results": results,
        "events": events,
        "pause_reason": spider.pause_reason,
        "pause_url_sha256": spider.pause_url_sha256,
        "remaining_count": len(urls) - len(results),
        "duration_ms": duration_ms,
        "cookie_metadata": cookie_metadata,
        "framework_paused": bool(crawl_result.paused),
        "framework_stats": crawl_result.stats.to_dict(),
    }


async def establish_scrapling_session(
    *,
    config: dict[str, Any],
    probe_url: str,
    session_dir: Path,
    session_ordinal: int,
) -> dict[str, Any]:
    """在全新隔离 profile 中登录并导出新的 Playwright storage state。"""

    session_dir.mkdir(parents=True, exist_ok=False)
    profile_dir = prepare_isolated_profile(session_dir / "browser-profile")
    candidate = config["candidate_a"]
    async with AsyncDynamicSession(
        headless=bool(config.get("headless", True)),
        google_search=False,
        max_pages=1,
        timeout=90_000,
        retries=1,
        user_data_dir=str(profile_dir),
        cookies=None,
        real_chrome=bool(candidate.get("real_chrome", False)),
    ) as session:
        login_result = await verify_login(
            session,
            probe_url,
            str(config["account"]),
            str(config["password"]),
            int(config.get("wait_ms", 1_000)),
            session_dir,
            bool(config.get("capture_login_diagnostic", True)),
        )
        storage_state = profile_dir / "storage-state.json"
        if login_result["logged_in"]:
            await session.context.storage_state(path=str(storage_state))
            storage_state.chmod(0o600)

    public_result = {
        **login_result,
        "session_ordinal": session_ordinal,
        "profile_mode": "fresh_isolated",
        "storage_state_written": storage_state.is_file(),
    }
    write_json(session_dir / "login-result.json", public_result)
    return {"success": bool(login_result["logged_in"] and storage_state.is_file()), "storage_state": storage_state}


def summarize_final_results(
    *,
    input_count: int,
    final_results: list[dict[str, Any]],
    request_events: list[dict[str, Any]],
    recovery_events: list[dict[str, Any]],
    duration_ms: int,
    remaining_count: int,
    stop_reason: str | None,
) -> dict[str, Any]:
    """汇总唯一最终结果和包含恢复尝试的真实请求量。"""

    success_count = sum(item["status"] == "success" for item in final_results)
    response_counts = Counter(str(item["response_class"]) for item in final_results)
    status_counts = Counter(str(item.get("http_status")) for item in final_results if item.get("http_status") is not None)
    recovered = sum(bool(event.get("trigger_recovered")) for event in recovery_events)
    refreshes = sum(event.get("event") == "session_refresh" for event in recovery_events)
    successful_refreshes = sum(
        event.get("event") == "session_refresh" and bool(event.get("success"))
        for event in recovery_events
    )
    request_count = len(request_events)
    return {
        "schema_version": "1.0",
        "candidate": "candidate-a",
        "mode": "bounded-session-recovery",
        "input_count": input_count,
        "final_result_count": len(final_results),
        "success_count": success_count,
        "remaining_count": remaining_count,
        "final_valid_rate": round(success_count / input_count, 6),
        "result_coverage_rate": round(len(final_results) / input_count, 6),
        "response_class_counts": dict(sorted(response_counts.items())),
        "http_status_counts": dict(sorted(status_counts.items())),
        "duration_ms": duration_ms,
        "effective_urls_per_second": round(success_count / (duration_ms / 1000), 6) if duration_ms else 0.0,
        "request_count": request_count,
        "request_amplification": round(request_count / input_count, 6),
        "request_metric_scope": "collector_http_gate_bulk_and_retry_excludes_browser_login_subrequests",
        "session_refresh_count": refreshes,
        "successful_session_refresh_count": successful_refreshes,
        "recovered_bulk_control_count": recovered,
        "stop_reason": stop_reason,
        "meets_correctness_gate": success_count == input_count and len(final_results) == input_count,
    }


def execute_recovery_control(
    *,
    urls: list[str],
    gate_urls: list[str],
    max_recoveries: int,
    deadline: float,
    initial_storage_state: Path | None,
    obtain_session: Callable[[int, str], dict[str, Any]],
    execute_segment: Callable[[list[str], Path, int, str], dict[str, Any]],
) -> dict[str, Any]:
    """执行可注入测试替身的有界 Session 恢复状态机。"""

    final_by_url: dict[str, dict[str, Any]] = {}
    request_events: list[dict[str, Any]] = []
    recovery_events: list[dict[str, Any]] = []
    remaining = list(urls)
    recovery_count = 0
    session_ordinal = 0
    stop_reason: str | None = None
    pending_trigger_url: str | None = None

    if initial_storage_state is not None:
        session_ordinal = 1
        current_state = initial_storage_state
        session_source = "provided"
    else:
        session_ordinal = 1
        opened = obtain_session(session_ordinal, "initial")
        if not opened["success"]:
            return {
                "final_results": [], "request_events": [], "recovery_events": [],
                "remaining_count": len(remaining), "stop_reason": "initial_login_failed",
            }
        current_state = Path(opened["storage_state"])
        session_source = "fresh_login"

    while remaining and time.monotonic() < deadline:
        try:
            gate = execute_segment(gate_urls, current_state, session_ordinal, "gate")
        except ValueError:
            gate = {
                "results": [],
                "events": [],
                "pause_reason": "session_state_unusable",
            }
        request_events.extend(gate["events"])
        gate_ok = len(gate["results"]) == len(gate_urls) and all(
            item["status"] == "success" for item in gate["results"]
        )
        recovery_events.append(
            {
                "event": "session_gate",
                "session_ordinal": session_ordinal,
                "session_source": session_source,
                "success": gate_ok,
                "result_count": len(gate["results"]),
                "response_class_counts": dict(Counter(item["response_class"] for item in gate["results"])),
            }
        )
        if not gate_ok:
            reason = str(gate.get("pause_reason") or "gate_failed")
            if reason in RECOVERABLE_SESSION_CLASSES and recovery_count < max_recoveries:
                recovery_count += 1
                session_ordinal += 1
                opened = obtain_session(session_ordinal, reason)
                recovery_events.append(
                    {"event": "session_refresh", "session_ordinal": session_ordinal, "reason": reason,
                     "recovery_scope": "gate", "success": bool(opened["success"]),
                     "trigger_recovered": False}
                )
                if not opened["success"]:
                    stop_reason = "session_refresh_failed"
                    break
                current_state = Path(opened["storage_state"])
                session_source = "recovery_login"
                continue
            stop_reason = reason if reason in NON_RECOVERABLE_CONTROL_CLASSES else "gate_failed"
            break

        try:
            segment = execute_segment(remaining, current_state, session_ordinal, "bulk")
        except ValueError:
            segment = {
                "results": [],
                "events": [],
                "pause_reason": "session_state_unusable",
            }
        request_events.extend(segment["events"])
        results = segment["results"]
        pause_reason = segment.get("pause_reason")

        if pending_trigger_url and results:
            first = results[0]
            if first["url"] == pending_trigger_url and first["response_class"] not in RECOVERABLE_SESSION_CLASSES:
                for event in reversed(recovery_events):
                    if event.get("event") == "session_refresh" and not event.get("trigger_recovered"):
                        event["trigger_recovered"] = True
                        break
                pending_trigger_url = None

        if pause_reason:
            if not results:
                if pause_reason in RECOVERABLE_SESSION_CLASSES and recovery_count < max_recoveries:
                    recovery_count += 1
                    session_ordinal += 1
                    opened = obtain_session(session_ordinal, str(pause_reason))
                    recovery_events.append(
                        {"event": "session_refresh", "session_ordinal": session_ordinal,
                         "reason": pause_reason, "recovery_scope": "bulk_state",
                         "success": bool(opened["success"]), "trigger_recovered": False}
                    )
                    if not opened["success"]:
                        stop_reason = "session_refresh_failed"
                        break
                    current_state = Path(opened["storage_state"])
                    session_source = "recovery_login"
                    continue
                stop_reason = (
                    "max_recoveries_exhausted"
                    if pause_reason in RECOVERABLE_SESSION_CLASSES
                    else str(pause_reason)
                )
                break
            control_result = results[-1]
            for result in results[:-1]:
                final_by_url[result["url"]] = result
            consumed_before_control = len(results) - 1
            remaining = remaining[consumed_before_control:]
            if pause_reason in RECOVERABLE_SESSION_CLASSES and recovery_count < max_recoveries:
                pending_trigger_url = str(control_result["url"])
                recovery_count += 1
                session_ordinal += 1
                opened = obtain_session(session_ordinal, str(pause_reason))
                recovery_events.append(
                    {"event": "session_refresh", "session_ordinal": session_ordinal,
                     "reason": pause_reason, "recovery_scope": "bulk_control",
                     "success": bool(opened["success"]),
                     "trigger_url_sha256": control_result["url_sha256"], "trigger_recovered": False}
                )
                if not opened["success"]:
                    final_by_url[control_result["url"]] = control_result
                    stop_reason = "session_refresh_failed"
                    break
                current_state = Path(opened["storage_state"])
                session_source = "recovery_login"
                continue
            final_by_url[control_result["url"]] = control_result
            stop_reason = (
                "max_recoveries_exhausted"
                if pause_reason in RECOVERABLE_SESSION_CLASSES
                else str(pause_reason)
            )
            break

        for result in results:
            final_by_url[result["url"]] = result
        remaining = remaining[len(results):]

    if remaining and stop_reason is None:
        stop_reason = "window_exhausted"
    ordered = [final_by_url[url] for url in urls if url in final_by_url]
    return {
        "final_results": ordered,
        "request_events": request_events,
        "recovery_events": recovery_events,
        "remaining_count": len(urls) - len(ordered),
        "stop_reason": stop_reason,
    }


def write_checksums(output_dir: Path) -> str:
    """为有界恢复的核心公开证据生成校验清单。"""

    names = [
        "environment.json", "input-urls.txt", "recovery-events.jsonl",
        "request-events.jsonl", "summary.json", "url-results.jsonl",
    ]
    lines = [f"{hashlib.sha256((output_dir / name).read_bytes()).hexdigest()}  {name}\n" for name in names]
    path = output_dir / "SHA256SUMS"
    path.write_text("".join(lines), encoding="utf-8", newline="\n")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    """执行有界登录恢复，并保证触发 URL 在新 Session 中重新处理。"""

    args = parse_args()
    config = load_config(args.config.resolve())
    urls, source_sha256 = load_selected_urls(args.input.resolve(), args.offset, args.limit)
    gate_urls = load_gate_urls(args.gate_input.resolve())
    args.output_dir.mkdir(parents=True, exist_ok=False)
    (args.output_dir / "input-urls.txt").write_text("\n".join(urls) + "\n", encoding="utf-8", newline="\n")
    started_at = utc_now()
    started = time.perf_counter()

    def obtain_session(session_ordinal: int, reason: str) -> dict[str, Any]:
        session_dir = args.output_dir / "sessions" / f"session-{session_ordinal:03d}"
        result = asyncio.run(
            establish_scrapling_session(
                config=config,
                probe_url=gate_urls[0],
                session_dir=session_dir,
                session_ordinal=session_ordinal,
            )
        )
        print(
            json.dumps(
                {"event": "session_refresh", "session_ordinal": session_ordinal,
                 "reason": reason, "success": result["success"]},
                ensure_ascii=False,
            ),
            flush=True,
        )
        return result

    def execute_segment(urls_: list[str], state: Path, ordinal: int, kind: str) -> dict[str, Any]:
        return run_http_segment(urls_, state, args.timeout_seconds, ordinal, kind)

    outcome = execute_recovery_control(
        urls=urls,
        gate_urls=gate_urls,
        max_recoveries=args.max_recoveries,
        deadline=started + args.window_seconds,
        initial_storage_state=args.initial_storage_state.resolve() if args.initial_storage_state else None,
        obtain_session=obtain_session,
        execute_segment=execute_segment,
    )
    duration_ms = round((time.perf_counter() - started) * 1000)
    summary = summarize_final_results(
        input_count=len(urls),
        final_results=outcome["final_results"],
        request_events=outcome["request_events"],
        recovery_events=outcome["recovery_events"],
        duration_ms=duration_ms,
        remaining_count=outcome["remaining_count"],
        stop_reason=outcome["stop_reason"],
    )
    environment = {
        "schema_version": "1.0",
        "candidate": "candidate-a",
        "mode": "bounded-session-recovery",
        "operating_system": platform.platform(),
        "python_version": platform.python_version(),
        "python_executable": str(Path(sys.executable).resolve()),
        "scrapling_version": scrapling.__version__,
        "started_at": started_at,
        "ended_at": utc_now(),
        "source_input_file_sha256": source_sha256,
        "selected_input_sha256": hashlib.sha256((args.output_dir / "input-urls.txt").read_bytes()).hexdigest(),
        "input_offset": args.offset,
        "input_count": len(urls),
        "gate_input_count": len(gate_urls),
        "max_recoveries": args.max_recoveries,
        "window_seconds": args.window_seconds,
        "concurrency": 1,
    }
    ItemList(outcome["final_results"]).to_jsonl(args.output_dir / "url-results.jsonl")
    write_jsonl(args.output_dir / "request-events.jsonl", outcome["request_events"])
    write_jsonl(args.output_dir / "recovery-events.jsonl", outcome["recovery_events"])
    write_json(args.output_dir / "summary.json", summary)
    write_json(args.output_dir / "environment.json", environment)
    summary["checksums_sha256"] = write_checksums(args.output_dir)
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary["meets_correctness_gate"] else 6


if __name__ == "__main__":
    raise SystemExit(main())
