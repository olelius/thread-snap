"""候选 A/B 共用的 PoC 结果契约与文档分类规则。"""

from __future__ import annotations

import hashlib
import html
import re
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

RESPONSE_CLASSES = {"post", "rate_limited", "captcha", "challenge", "login", "empty", "error"}
CHANNELS = {"http", "browser-network", "browser-dom"}
STATUSES = {"success", "partial", "failed", "blocked"}
POST_ID_PATH_RE = re.compile(r"/ugc/article/(\d+)(?:/|$)")
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
TAG_RE = re.compile(r"<[^>]+>")


def url_sha256(url: str) -> str:
    """生成 URL 的稳定标识，日志和控制台优先输出该值。"""

    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def extract_input_post_id(url: str) -> str:
    """从当前首个平台的帖子 URL 路径中提取帖子 ID。"""

    parsed = urlsplit(url)
    match = POST_ID_PATH_RE.search(parsed.path)
    if not match:
        raise ValueError("URL 路径不符合 /ugc/article/<post-id> 结构")
    return match.group(1)


def visible_text(document: str) -> str:
    """移除脚本、样式和标签，生成仅用于存在性判断的可见文本。"""

    without_scripts = SCRIPT_STYLE_RE.sub(" ", document)
    return re.sub(r"\s+", " ", html.unescape(TAG_RE.sub(" ", without_scripts))).strip()


def classify_document(final_url: str, http_status: int | None, document: str, input_post_id: str) -> dict[str, Any]:
    """按跨候选统一规则分类最终响应，避免只凭 HTTP 200 判成功。"""

    lowered = document.lower()
    final_lower = final_url.lower()
    text = visible_text(document)
    title_match = TITLE_RE.search(document)
    title = visible_text(title_match.group(1)) if title_match else ""

    if http_status == 429 or "rate limit" in lowered or "请求过于频繁" in document:
        response_class = "rate_limited"
    elif "/login-required" in final_lower or "login-required" in lowered or "请登录" in document:
        response_class = "login"
    elif "captcha" in lowered or "验证码" in document:
        response_class = "captcha"
    elif "_$jsvmprt" in document or "secsdk-captcha" in lowered or "challenge-platform" in lowered:
        response_class = "challenge"
    elif http_status is None or http_status >= 400:
        response_class = "error"
    elif not text:
        response_class = "empty"
    else:
        response_class = "post"

    title_present = bool(title) and response_class == "post"
    body_present = response_class == "post" and len(text) >= 40
    # 登录/挑战页可能在 redirect 参数中回显输入 ID；这不是平台帖子标识证据。
    observed_post_id = input_post_id if response_class == "post" and input_post_id in document else None
    post_id_matches = observed_post_id == input_post_id

    if response_class == "post" and post_id_matches and (title_present or body_present):
        status = "success"
    elif response_class == "post":
        status = "partial"
    elif response_class in {"rate_limited", "captcha", "challenge", "login"}:
        status = "blocked"
    else:
        status = "failed"

    return {
        "observed_post_id": observed_post_id,
        "post_id_matches": post_id_matches,
        "title_present": title_present,
        "body_present": body_present,
        "response_class": response_class,
        "status": status,
    }


def parse_iso8601(value: str) -> datetime:
    """解析必须带时区的 ISO 8601 时间。"""

    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("时间缺少时区")
    return parsed


def validate_result(record: dict[str, Any], candidate: str) -> list[str]:
    """验证单条结果的字段、类型和交叉一致性，返回全部错误。"""

    errors: list[str] = []
    required = {
        "schema_version",
        "candidate",
        "url",
        "url_sha256",
        "input_post_id",
        "observed_post_id",
        "post_id_matches",
        "title_present",
        "body_present",
        "response_class",
        "control_hit",
        "channel",
        "status",
        "request_count",
        "started_at",
        "ended_at",
        "duration_ms",
        "http_status",
        "error_category",
    }
    missing = sorted(required - record.keys())
    if missing:
        return [f"缺少字段: {', '.join(missing)}"]

    if record["schema_version"] != "1.0":
        errors.append("schema_version 必须为 1.0")
    if record["candidate"] != candidate:
        errors.append("candidate 与命令行期望不一致")
    if record["response_class"] not in RESPONSE_CLASSES:
        errors.append("response_class 非法")
    if record["channel"] not in CHANNELS:
        errors.append("channel 非法")
    if record["status"] not in STATUSES:
        errors.append("status 非法")

    try:
        expected_post_id = extract_input_post_id(record["url"])
        if record["input_post_id"] != expected_post_id:
            errors.append("input_post_id 与 URL 不一致")
    except (TypeError, ValueError) as exc:
        errors.append(str(exc))
    if record["url_sha256"] != url_sha256(record["url"]):
        errors.append("url_sha256 与 URL 不一致")

    bool_fields = ("post_id_matches", "title_present", "body_present", "control_hit")
    for field in bool_fields:
        if not isinstance(record[field], bool):
            errors.append(f"{field} 必须为布尔值")
    if not isinstance(record["request_count"], int) or isinstance(record["request_count"], bool) or record["request_count"] < 1:
        errors.append("request_count 必须为正整数")
    if not isinstance(record["duration_ms"], int) or isinstance(record["duration_ms"], bool) or record["duration_ms"] < 0:
        errors.append("duration_ms 必须为非负整数")
    if record["http_status"] is not None and (
        not isinstance(record["http_status"], int) or isinstance(record["http_status"], bool) or not 100 <= record["http_status"] <= 599
    ):
        errors.append("http_status 必须为 null 或 100..599")

    try:
        started = parse_iso8601(record["started_at"])
        ended = parse_iso8601(record["ended_at"])
        if ended < started:
            errors.append("ended_at 早于 started_at")
    except (TypeError, ValueError) as exc:
        errors.append(f"时间格式错误: {exc}")

    proof = record["title_present"] or record["body_present"]
    if record["status"] == "success":
        if record["response_class"] != "post" or not record["post_id_matches"] or not proof:
            errors.append("success 必须同时满足 post、帖子 ID 匹配和内容证明")
        if record["observed_post_id"] != record["input_post_id"]:
            errors.append("success 的 observed_post_id 必须等于 input_post_id")
        if record["error_category"] is not None:
            errors.append("success 不得包含 error_category")
    if record["response_class"] in {"rate_limited", "captcha", "challenge", "login"}:
        if record["status"] != "blocked":
            errors.append("未恢复的平台控制响应必须标记 blocked")
        if not record["control_hit"]:
            errors.append("平台控制响应必须设置 control_hit=true")
    if record["status"] == "blocked" and record["response_class"] not in {"rate_limited", "captcha", "challenge", "login"}:
        errors.append("blocked 必须对应平台控制响应")
    return errors
