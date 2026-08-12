"""用已登录浏览器的 storage state 执行首版认证纯 HTTP 探针。"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
import time
from pathlib import Path

import scrapling
from scrapling.spiders.result import ItemList

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "poc" / "shared"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from contract import extract_input_post_id, validate_result  # noqa: E402
from http_throughput import (  # noqa: E402
    DirectHttpSpider,
    build_summary,
    utc_now,
    write_checksums,
    write_json,
    write_jsonl,
)
from session_handoff import load_http_cookies  # noqa: E402


def parse_args() -> argparse.Namespace:
    """解析认证 HTTP 小样本入口参数。"""

    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--storage-state", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--timeout-seconds", type=int, default=30)
    args = parser.parse_args()
    if not 1 <= args.limit <= 2000:
        parser.error("认证 HTTP 探针的 limit 必须在 1 到 2000 之间")
    if args.offset < 0:
        parser.error("offset 不能为负数")
    if args.timeout_seconds < 1:
        parser.error("timeout-seconds 必须为正整数")
    return args


def infer_risk(summary: dict, session_metadata: dict) -> dict:
    """根据响应分类生成不含凭证的首轮原因判断。"""

    counts = summary["response_class_counts"]
    http_status_counts = summary.get("http_status_counts", {})
    failure_count = summary["result_count"] - summary["success_count"]
    if summary["success_count"] == summary["result_count"]:
        category = "authenticated_http_viable_for_small_sample"
        evidence = "全部样本通过帖子 ID 与正文证据校验"
    elif failure_count > 0 and int(http_status_counts.get("404", 0)) == failure_count:
        category = "input_not_found"
        evidence = "全部失败项均为服务端 HTTP 404；未观察到登录、验证码、挑战、限流或空文档"
    elif counts.get("login", 0):
        category = "session_rejected_or_incomplete"
        evidence = "服务端仍返回登录态页面；需核对 Cookie 完整性、域、有效期及会话绑定"
    elif counts.get("captcha", 0) or counts.get("challenge", 0):
        category = "interactive_risk_control_triggered"
        evidence = "响应出现验证码或挑战页特征；当前请求身份或访问行为触发校验"
    elif counts.get("rate_limited", 0):
        category = "request_rate_limited"
        evidence = "响应出现限流状态；首版并发为 1，优先检查账号/IP 历史状态而非继续提速"
    elif counts.get("empty", 0):
        category = "content_not_proven"
        evidence = "响应没有足够正文证据，不能把 HTTP 200 计为有效采集"
    else:
        category = "transport_or_unclassified_failure"
        evidence = "请求错误或页面形态尚未被分类器识别"
    return {
        "category": category,
        "evidence": evidence,
        "cookie_transfer": {
            "source_cookie_count": session_metadata["source_cookie_count"],
            "accepted_cookie_count": session_metadata["accepted_cookie_count"],
            "expired_cookie_count": session_metadata["expired_cookie_count"],
            "unrelated_cookie_count": session_metadata["unrelated_cookie_count"],
            "malformed_cookie_count": session_metadata["malformed_cookie_count"],
        },
        "limits": [
            "本轮只能区分响应层面的风控类别，不能证明平台内部具体评分规则",
            "Cookie 值和名称未写入结果或日志",
        ],
    }


def was_stopped_by_policy(framework_paused: bool, pause_reason: str | None) -> bool:
    """兼容框架快速收口时暂停标志尚未置位的情况。"""

    return framework_paused or pause_reason is not None


def main() -> int:
    """执行最多三条、并发为一、无自动重试的认证 HTTP 验证。"""

    args = parse_args()
    all_urls = [line.strip() for line in args.input.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    if args.offset + args.limit > len(all_urls):
        raise ValueError("offset + limit 超出输入清单范围")
    urls = all_urls[args.offset : args.offset + args.limit]
    for url in urls:
        extract_input_post_id(url)
    hosts = {(url.split("/", 3)[2]).lower() for url in urls}
    if len(hosts) != 1:
        raise ValueError("首版认证 HTTP 探针只接受同一主机的样本")

    cookies, session_metadata = load_http_cookies(args.storage_state.resolve(), urls[0])
    args.output_dir.mkdir(parents=True, exist_ok=False)
    (args.output_dir / "input-urls.txt").write_text("\n".join(urls) + "\n", encoding="utf-8", newline="\n")

    started_at = utc_now()
    started_perf = time.perf_counter()
    spider = DirectHttpSpider(
        urls,
        concurrency=1,
        timeout_seconds=args.timeout_seconds,
        request_cookies=cookies,
        pause_on_control=True,
    )
    crawl_result = spider.start()
    duration_ms = round((time.perf_counter() - started_perf) * 1000)

    missing = [url for url in urls if url not in spider.results_by_url]
    stopped_by_policy = was_stopped_by_policy(crawl_result.paused, spider.pause_reason)
    if missing and not stopped_by_policy:
        raise RuntimeError(f"Spider 缺少 {len(missing)} 条结果")
    completed_urls = [url for url in urls if url in spider.results_by_url]
    results = [spider.results_by_url[url] for url in completed_urls]
    events = [spider.events_by_url[url] for url in completed_urls]
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
        concurrency=1,
        access_mode="authenticated-direct-http",
        requested_count=len(urls),
    )
    summary["crawl_paused"] = stopped_by_policy
    summary["framework_paused"] = crawl_result.paused
    summary["remaining_count"] = len(missing)
    summary["stop_policy"] = "pause_after_first_control_or_empty"
    summary["stop_reason"] = spider.pause_reason
    summary["stop_url_sha256"] = spider.pause_url_sha256
    summary["risk_analysis"] = infer_risk(summary, session_metadata)
    environment = {
        "schema_version": "1.0",
        "candidate": "candidate-a",
        "access_mode": "authenticated-direct-http",
        "operating_system": platform.platform(),
        "python_version": platform.python_version(),
        "python_executable": str(Path(sys.executable).resolve()),
        "scrapling_version": scrapling.__version__,
        "started_at": started_at,
        "ended_at": utc_now(),
        "input_count": len(urls),
        "input_file_sha256": hashlib.sha256((args.output_dir / "input-urls.txt").read_bytes()).hexdigest(),
        "source_input_file_sha256": hashlib.sha256(args.input.read_bytes()).hexdigest(),
        "input_offset": args.offset,
        "concurrency": 1,
        "browser_started": False,
        "session_cookie_metadata": session_metadata,
        "framework_crawl_stats": crawl_result.stats.to_dict(),
    }
    ItemList(results).to_jsonl(args.output_dir / "url-results.jsonl")
    write_jsonl(args.output_dir / "request-events.jsonl", events)
    write_json(args.output_dir / "summary.json", summary)
    write_json(args.output_dir / "environment.json", environment)
    write_checksums(args.output_dir)
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary["meets_correctness_gate"] else 6


if __name__ == "__main__":
    raise SystemExit(main())
