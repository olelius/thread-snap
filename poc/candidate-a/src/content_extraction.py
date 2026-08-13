"""Candidate A：用 Scrapling Spider 从帖子 JSON API 提取第一版业务字段。"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import platform
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncGenerator, Iterable
from urllib.parse import urlencode

import scrapling
from curl_cffi.requests import Cookies
from scrapling.fetchers import FetcherSession
from scrapling.spiders import Request, Response, SessionManager, Spider
from scrapling.spiders.result import ItemList

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "poc" / "shared"))

from contract import classify_document, extract_input_post_id, url_sha256  # noqa: E402
from http_throughput import percentile, utc_now, write_json  # noqa: E402
from session_handoff import load_http_cookies  # noqa: E402

API_ROOT = "https://www.dongchedi.com/motor/pc/ugc/detail"
API_COMMON = {"aid": "1839", "app_name": "auto_web_pc"}
MAX_FIRST_LEVEL_COMMENTS = 10
API_CONTROL_CLASSES = frozenset({"login", "captcha", "challenge", "rate_limited", "empty", "error"})


def api_url(endpoint: str, **params: object) -> str:
    """生成无动态签名的帖子 API URL。"""

    query = {**API_COMMON, **{key: str(value) for key, value in params.items() if value is not None}}
    return f"{API_ROOT}/{endpoint}?{urlencode(query)}"


def epoch_to_iso8601(value: object) -> str | None:
    """把平台秒级时间戳转换为 UTC ISO 8601；无效值返回空。"""

    if isinstance(value, bool):
        return None
    try:
        timestamp = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None
    if timestamp <= 0:
        return None
    try:
        return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()
    except (OSError, OverflowError, ValueError):
        return None


def unique_urls(values: Iterable[object]) -> list[str]:
    """按出现顺序去重合法 HTTP(S) URL。"""

    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not value.startswith(("http://", "https://")) or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def extract_video_urls(data: dict[str, Any]) -> list[str]:
    """从详情响应的显式视频字段和 video_play_info 中提取播放 URL。"""

    candidates: list[object] = []
    for key in ("video_url", "video_urls"):
        value = data.get(key)
        candidates.extend(value if isinstance(value, list) else [value])

    play_info: Any = data.get("video_play_info")
    if isinstance(play_info, str) and play_info.strip():
        try:
            play_info = json.loads(play_info)
        except json.JSONDecodeError:
            play_info = None

    def walk(value: Any, path: str = "") -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                walk(child, f"{path}.{key}" if path else str(key))
        elif isinstance(value, list):
            for child in value:
                walk(child, path)
        elif isinstance(value, str) and value.startswith(("http://", "https://")):
            lowered = path.lower()
            if any(marker in lowered for marker in ("play", "video", "main_url", "backup_url", "url_list")):
                candidates.append(value)

    walk(play_info)
    return unique_urls(candidates)


def normalize_detail(input_url: str, payload: dict[str, Any]) -> dict[str, Any]:
    """把详情 API 响应映射为第一版帖子业务字段。"""

    input_post_id = extract_input_post_id(input_url)
    api_status = payload.get("status")
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    profile = data.get("motor_profile_info") if isinstance(data.get("motor_profile_info"), dict) else {}
    car_info = data.get("motor_car_info") if isinstance(data.get("motor_car_info"), dict) else {}
    observed_post_id = str(data.get("group_id_str") or data.get("group_id") or "") or None
    body = str(data.get("content") or data.get("motor_title") or "").strip()
    title = str(data.get("thread_title") or "").strip() or None
    author = str(profile.get("name") or "").strip() or None

    image_items = data.get("image_urls") if isinstance(data.get("image_urls"), list) else []
    image_urls = unique_urls(
        item.get("url") if isinstance(item, dict) else item
        for item in image_items
    )
    reply_count = data.get("comment_count") if isinstance(data.get("comment_count"), int) else None
    like_count = data.get("digg_count") if isinstance(data.get("digg_count"), int) else None
    section = str(
        car_info.get("source_desc") or car_info.get("motor_name") or car_info.get("series_name") or ""
    ).strip() or None
    published_at = epoch_to_iso8601(data.get("content_publish_time") or data.get("created_time"))
    operation_status = data.get("operation_status")
    is_visible = api_status == 0 and observed_post_id == input_post_id and operation_status == 0
    normalized_status = "visible" if is_visible else "unknown"

    missing_fields: list[str] = []
    if observed_post_id != input_post_id:
        missing_fields.append("platform_post_id")
    if not body:
        missing_fields.append("body")
    if published_at is None:
        missing_fields.append("published_at")
    if reply_count is None:
        missing_fields.append("reply_count")
    if like_count is None:
        missing_fields.append("like_count")
    if normalized_status == "unknown":
        missing_fields.append("visible_status")

    if api_status != 0:
        error_category = "detail_api_error"
    elif observed_post_id != input_post_id:
        error_category = "detail_not_found"
    else:
        error_category = None

    return {
        "schema_version": "1.0",
        "candidate": "candidate-a",
        "url": input_url,
        "url_sha256": url_sha256(input_url),
        "platform_post_id": observed_post_id,
        "post_id_matches": observed_post_id == input_post_id,
        "title": title,
        "author": author,
        "published_at": published_at,
        "body": body,
        "image_urls": image_urls,
        "video_urls": extract_video_urls(data),
        "reply_count": reply_count,
        "like_count": like_count,
        "section": section,
        "visible_status": normalized_status,
        "raw_status": {
            "api_status": api_status,
            "api_message": payload.get("message"),
            "operation_status": operation_status,
            "visibility_level": data.get("visibility_level"),
        },
        "detail_http_status": None,
        "comment_http_statuses": [],
        "comments": [],
        "comments_complete": reply_count == 0,
        "comment_api_total_count": 0 if reply_count == 0 else None,
        "comment_count_consistent": True if reply_count == 0 else None,
        "missing_fields": missing_fields,
        "status": "success" if not missing_fields else "partial",
        "error_category": error_category,
    }


def normalize_comment(item: object) -> dict[str, Any] | None:
    """映射一条一级评论；无评论 ID 的异常项不计入结果。"""

    if not isinstance(item, dict):
        return None
    comment_id = str(item.get("comment_id_str") or item.get("comment_id") or "").strip()
    if not comment_id:
        return None
    profile = item.get("profile_info") if isinstance(item.get("profile_info"), dict) else {}
    return {
        "comment_id": comment_id,
        "author": str(profile.get("name") or "").strip() or None,
        "content": str(item.get("text") or "").strip(),
        "published_at": epoch_to_iso8601(item.get("create_time")),
        "like_count": item.get("digg_count") if isinstance(item.get("digg_count"), int) else None,
    }


def comment_page(payload: dict[str, Any]) -> dict[str, Any]:
    """解析评论页的一级评论、分页游标与完整性证据。"""

    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    raw_items = data.get("comment_data") if isinstance(data.get("comment_data"), list) else []
    comments = [comment for item in raw_items if (comment := normalize_comment(item)) is not None]
    return {
        "api_ok": payload.get("status") == 0,
        "comments": comments,
        "cursor": data.get("cursor"),
        "has_more": data.get("has_more") is True,
        "total_count": data.get("total_count") if isinstance(data.get("total_count"), int) else None,
    }


def comment_collection_complete(*, collected_count: int, has_more: bool) -> bool:
    """达到十条或接口明确无下一页时，以本次实际返回评论作为最终结果。"""

    return collected_count >= MAX_FIRST_LEVEL_COMMENTS or not has_more


def response_payload(response: Response) -> dict[str, Any]:
    """直接从原始字节解析 JSON，避免响应头编码导致中文失真。"""

    try:
        payload = json.loads(response.body)
    except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def classify_api_error(url: str, http_status: int, body: bytes, input_post_id: str) -> str:
    """识别 API 返回的登录、验证码、挑战、限流和空响应；其他异常归为 API 错误。"""

    document = body.decode("utf-8", errors="replace")
    response_class = classify_document(url, http_status, document, input_post_id)["response_class"]
    return response_class if response_class in API_CONTROL_CLASSES else "api_error"


def finalize_record(
    record: dict[str, Any],
    *,
    started_perf: float,
    request_count: int,
    api_durations_ms: list[int],
    comments_error: str | None = None,
) -> dict[str, Any]:
    """补齐性能、请求放大和最终完整性字段。"""

    if comments_error:
        record["comments_complete"] = False
        if "comments" not in record["missing_fields"]:
            record["missing_fields"].append("comments")
        record["error_category"] = comments_error
    record["request_count"] = request_count
    record["api_durations_ms"] = api_durations_ms
    record["duration_ms"] = round((time.perf_counter() - started_perf) * 1000)
    record["status"] = "success" if not record["missing_fields"] and record["comments_complete"] else "partial"
    return record


class ContentExtractionSpider(Spider):
    """先详情、后按需评论的 Scrapling HTTP Spider。"""

    name = "threadsnap-candidate-a-content-extraction"
    max_blocked_retries = 0
    logging_level = logging.WARNING
    autothrottle_enabled = False

    def __init__(
        self,
        urls: list[str],
        *,
        concurrency: int,
        timeout_seconds: int,
        request_cookies: Cookies,
    ) -> None:
        self.urls = urls
        self.concurrent_requests = concurrency
        self.concurrent_requests_per_domain = concurrency
        self.timeout_seconds = timeout_seconds
        self.request_cookies = request_cookies
        self.results_by_url: dict[str, dict[str, Any]] = {}
        self.run_started_perf = time.perf_counter()
        self.completion_offsets_ms: dict[str, int] = {}
        super().__init__()

    def configure_sessions(self, manager: SessionManager) -> None:
        """注册唯一 FetcherSession；框架只尝试一次，避免隐式重复请求。"""

        manager.add(
            "http",
            FetcherSession(
                impersonate="chrome",
                stealthy_headers=True,
                timeout=self.timeout_seconds,
                retries=1,
                retry_delay=0,
                follow_redirects="safe",
            ),
            default=True,
        )

    async def start_requests(self) -> AsyncGenerator[Request, None]:
        """每个帖子只先请求一次详情 API，不访问页面 DOM。"""

        for input_url in self.urls:
            post_id = extract_input_post_id(input_url)
            yield Request(
                api_url("common", group_id=post_id),
                sid="http",
                callback=self.parse_detail,
                cookies=self.request_cookies,
                meta={
                    "input_url": input_url,
                    "started_perf": time.perf_counter(),
                    "request_count": 1,
                    "api_durations_ms": [],
                    "request_started_perf": time.perf_counter(),
                },
            )

    async def is_blocked(self, response: Response) -> bool:
        """保留阻断终态给业务解析，不让框架自动吞掉响应或重试。"""

        return False

    async def parse(self, response: Response) -> AsyncGenerator[dict[str, Any] | Request | None, None]:
        """满足 Spider 默认回调契约，并把响应委托给详情解析器。"""

        async for item in self.parse_detail(response):
            yield item

    def _complete(self, input_url: str, record: dict[str, Any]) -> None:
        self.results_by_url[input_url] = record
        self.completion_offsets_ms[input_url] = round((time.perf_counter() - self.run_started_perf) * 1000)

    async def parse_detail(self, response: Response) -> AsyncGenerator[dict[str, Any] | Request | None, None]:
        """解析详情；只有平台报告存在评论时才调评论 API。"""

        request = response.request
        if request is None:
            raise RuntimeError("详情响应缺少原始请求")
        input_url = str(request.meta["input_url"])
        started_perf = float(request.meta["started_perf"])
        durations = list(request.meta["api_durations_ms"])
        durations.append(round((time.perf_counter() - float(request.meta["request_started_perf"])) * 1000))
        payload = response_payload(response)
        record = normalize_detail(input_url, payload)
        record["detail_http_status"] = int(response.status)
        record["comment_http_statuses"] = []
        if int(response.status) != 200 or payload.get("status") != 0:
            record["missing_fields"] = sorted(set(record["missing_fields"] + ["detail_api"]))
            error_category = classify_api_error(
                str(response.url),
                int(response.status),
                response.body,
                extract_input_post_id(input_url),
            )
            final = finalize_record(
                record,
                started_perf=started_perf,
                request_count=1,
                api_durations_ms=durations,
                comments_error=error_category,
            )
            self._complete(input_url, final)
            yield final
            return

        reply_count = record.get("reply_count")
        if not record["post_id_matches"] or not isinstance(reply_count, int):
            final = finalize_record(
                record,
                started_perf=started_perf,
                request_count=1,
                api_durations_ms=durations,
                comments_error="detail_not_found",
            )
            self._complete(input_url, final)
            yield final
            return
        if reply_count == 0:
            final = finalize_record(record, started_perf=started_perf, request_count=1, api_durations_ms=durations)
            self._complete(input_url, final)
            yield final
            return

        post_id = extract_input_post_id(input_url)
        yield Request(
            api_url("comment_list", group_id=post_id, count=MAX_FIRST_LEVEL_COMMENTS, cursor=0),
            sid="http",
            callback=self.parse_comments,
            cookies=self.request_cookies,
            meta={
                "input_url": input_url,
                "record": record,
                "started_perf": started_perf,
                "request_count": 2,
                "api_durations_ms": durations,
                "comments": [],
                "request_started_perf": time.perf_counter(),
            },
        )

    async def parse_comments(self, response: Response) -> AsyncGenerator[dict[str, Any] | Request | None, None]:
        """解析一级评论；首批不足 10 且确有下一页时才继续。"""

        request = response.request
        if request is None:
            raise RuntimeError("评论响应缺少原始请求")
        meta = request.meta
        input_url = str(meta["input_url"])
        record = dict(meta["record"])
        started_perf = float(meta["started_perf"])
        request_count = int(meta["request_count"])
        durations = list(meta["api_durations_ms"])
        durations.append(round((time.perf_counter() - float(meta["request_started_perf"])) * 1000))
        payload = response_payload(response)
        page = comment_page(payload)
        record["comment_http_statuses"] = [*record.get("comment_http_statuses", []), int(response.status)]
        comments = list(meta["comments"])
        seen = {item["comment_id"] for item in comments}
        for item in page["comments"]:
            if item["comment_id"] not in seen and len(comments) < MAX_FIRST_LEVEL_COMMENTS:
                comments.append(item)
                seen.add(item["comment_id"])

        if int(response.status) != 200 or not page["api_ok"]:
            record["comments"] = comments
            error_category = classify_api_error(
                str(response.url),
                int(response.status),
                response.body,
                extract_input_post_id(input_url),
            )
            final = finalize_record(
                record,
                started_perf=started_perf,
                request_count=request_count,
                api_durations_ms=durations,
                comments_error=error_category,
            )
            self._complete(input_url, final)
            yield final
            return

        total_count = page["total_count"]
        record["comment_api_total_count"] = total_count
        record["comment_count_consistent"] = total_count is not None and record.get("reply_count") == total_count
        collection_complete = comment_collection_complete(
            collected_count=len(comments),
            has_more=bool(page["has_more"]),
        )
        if collection_complete:
            record["comments"] = comments[:MAX_FIRST_LEVEL_COMMENTS]
            record["comments_complete"] = True
            final = finalize_record(
                record,
                started_perf=started_perf,
                request_count=request_count,
                api_durations_ms=durations,
                comments_error=None,
            )
            self._complete(input_url, final)
            yield final
            return

        cursor = page["cursor"]
        if cursor is None:
            record["comments"] = comments
            final = finalize_record(
                record,
                started_perf=started_perf,
                request_count=request_count,
                api_durations_ms=durations,
                comments_error="comments_cursor_missing",
            )
            self._complete(input_url, final)
            yield final
            return

        post_id = extract_input_post_id(input_url)
        yield Request(
            api_url(
                "comment_list",
                group_id=post_id,
                count=MAX_FIRST_LEVEL_COMMENTS - len(comments),
                cursor=cursor,
            ),
            sid="http",
            callback=self.parse_comments,
            cookies=self.request_cookies,
            meta={
                "input_url": input_url,
                "record": record,
                "started_perf": started_perf,
                "request_count": request_count + 1,
                "api_durations_ms": durations,
                "comments": comments,
                "request_started_perf": time.perf_counter(),
            },
        )

    async def on_error(self, request: Request, error: Exception) -> None:
        """把请求异常收敛为唯一帖子终态，避免缺失结果。"""

        input_url = str(request.meta.get("input_url", request.url))
        started_perf = float(request.meta.get("started_perf", time.perf_counter()))
        record = request.meta.get("record")
        if not isinstance(record, dict):
            record = normalize_detail(input_url, {})
        record = dict(record)
        record["comments"] = list(request.meta.get("comments", []))
        final = finalize_record(
            record,
            started_perf=started_perf,
            request_count=int(request.meta.get("request_count", 1)),
            api_durations_ms=list(request.meta.get("api_durations_ms", [])),
            comments_error=type(error).__name__,
        )
        self._complete(input_url, final)


def build_content_summary(results: list[dict[str, Any]], duration_ms: int, concurrency: int) -> dict[str, Any]:
    """统计内容完整率、真实空评论和有效速度。"""

    complete_count = sum(item["status"] == "success" for item in results)
    request_count = sum(int(item["request_count"]) for item in results)
    durations = [int(item["duration_ms"]) for item in results]
    missing = Counter(field for item in results for field in item["missing_fields"])
    true_empty_comments = sum(item.get("reply_count") == 0 and item.get("comments_complete") for item in results)
    comments = [comment for item in results for comment in item["comments"]]
    error_categories = Counter(str(item["error_category"]) for item in results if item.get("error_category"))
    return {
        "schema_version": "1.0",
        "candidate": "candidate-a",
        "mode": "content-extraction-http-api",
        "input_count": len(results),
        "result_count": len(results),
        "complete_count": complete_count,
        "content_completeness_rate": round(complete_count / len(results), 6) if results else 0,
        "comments_complete_count": sum(bool(item["comments_complete"]) for item in results),
        "true_empty_comment_count": true_empty_comments,
        "comment_count_mismatch_count": sum(item.get("comment_count_consistent") is False for item in results),
        "comment_count_unknown_count": sum(item.get("comment_count_consistent") is None for item in results),
        "detail_not_found_count": sum(item.get("error_category") == "detail_not_found" for item in results),
        "body_present_count": sum(bool(item["body"]) for item in results),
        "title_present_count": sum(bool(item["title"]) for item in results),
        "author_present_count": sum(bool(item["author"]) for item in results),
        "section_present_count": sum(bool(item["section"]) for item in results),
        "posts_with_images_count": sum(bool(item["image_urls"]) for item in results),
        "image_url_count": sum(len(item["image_urls"]) for item in results),
        "posts_with_videos_count": sum(bool(item["video_urls"]) for item in results),
        "video_url_count": sum(len(item["video_urls"]) for item in results),
        "comment_extracted_count": len(comments),
        "comment_empty_optional_field_counts": {
            field: sum(comment.get(field) in (None, "") for comment in comments)
            for field in ("author", "content", "published_at", "like_count")
        },
        "missing_field_counts": dict(sorted(missing.items())),
        "error_category_counts": dict(sorted(error_categories.items())),
        "duration_ms": duration_ms,
        "effective_complete_urls_per_second": round(complete_count / (duration_ms / 1000), 6) if duration_ms else 0,
        "processed_urls_per_second": round(len(results) / (duration_ms / 1000), 6) if duration_ms else 0,
        "p50_duration_ms": percentile(durations, 0.50),
        "p95_duration_ms": percentile(durations, 0.95),
        "request_count": request_count,
        "request_amplification": round(request_count / len(results), 6) if results else 0,
        "single_request_count": sum(item["request_count"] == 1 for item in results),
        "concurrency": concurrency,
        "page_document_requests": 0,
        "browser_started": False,
        "dynamic_signature_required": False,
    }


def write_content_checksums(output_dir: Path) -> None:
    """为内容提取核心产物写 SHA-256 清单，不复制结果文件。"""

    names = ["content-results.jsonl", "environment.json", "input-urls.txt", "summary.json"]
    lines = [f"{hashlib.sha256((output_dir / name).read_bytes()).hexdigest()}  {name}\n" for name in names]
    (output_dir / "SHA256SUMS").write_text("".join(lines), encoding="utf-8", newline="\n")


def parse_args() -> argparse.Namespace:
    """解析内容提取测试参数。"""

    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--storage-state", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--timeout-seconds", type=int, default=20)
    args = parser.parse_args()
    if args.limit < 1 or args.offset < 0 or args.concurrency < 1 or args.timeout_seconds < 1:
        parser.error("limit、concurrency、timeout-seconds 必须为正整数，offset 必须为非负整数")
    return args


def main() -> int:
    """运行 API 内容提取并输出逐帖字段与完整性/速度摘要。"""

    args = parse_args()
    all_urls = [line.strip() for line in args.input.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    if args.offset + args.limit > len(all_urls):
        raise ValueError("offset + limit 超出输入清单范围")
    urls = all_urls[args.offset : args.offset + args.limit]
    for url in urls:
        extract_input_post_id(url)
    if len(set(urls)) != len(urls):
        raise ValueError("内容提取测试清单包含重复 URL")

    cookies, cookie_metadata = load_http_cookies(args.storage_state.resolve(), urls[0])
    args.output_dir.mkdir(parents=True, exist_ok=False)
    (args.output_dir / "input-urls.txt").write_text("\n".join(urls) + "\n", encoding="utf-8", newline="\n")

    started_at = utc_now()
    started_perf = time.perf_counter()
    spider = ContentExtractionSpider(
        urls,
        concurrency=args.concurrency,
        timeout_seconds=args.timeout_seconds,
        request_cookies=cookies,
    )
    crawl_result = spider.start()
    duration_ms = round((time.perf_counter() - started_perf) * 1000)
    missing_urls = [url for url in urls if url not in spider.results_by_url]
    if missing_urls:
        raise RuntimeError(f"Spider 缺少 {len(missing_urls)} 条最终结果")
    results = [spider.results_by_url[url] for url in urls]
    summary = build_content_summary(results, duration_ms, args.concurrency)
    environment = {
        "schema_version": "1.0",
        "candidate": "candidate-a",
        "mode": "content-extraction-http-api",
        "operating_system": platform.platform(),
        "python_version": platform.python_version(),
        "python_executable": str(Path(sys.executable).resolve()),
        "scrapling_version": scrapling.__version__,
        "started_at": started_at,
        "ended_at": utc_now(),
        "input_count": len(urls),
        "input_offset": args.offset,
        "concurrency": args.concurrency,
        "browser_started": False,
        "page_document_requests": 0,
        "session_cookie_metadata": cookie_metadata,
        "framework_crawl_stats": crawl_result.stats.to_dict(),
    }
    ItemList(results).to_jsonl(args.output_dir / "content-results.jsonl")
    write_json(args.output_dir / "summary.json", summary)
    write_json(args.output_dir / "environment.json", environment)
    write_content_checksums(args.output_dir)
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary["complete_count"] == summary["input_count"] else 6


if __name__ == "__main__":
    raise SystemExit(main())
