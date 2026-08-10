"""为访问失败保存不含页面正文和 Cookie 值的结构化诊断。"""

from __future__ import annotations

import hashlib
import html
import re
from typing import Any, Iterable, Mapping
from urllib.parse import urlsplit

ACCESS_DIAGNOSTIC_CLASSES = frozenset({"login", "empty"})
ACCESS_DIAGNOSTIC_LIMIT_PER_CLASS = 3
ACCESS_MARKERS = (
    ("login_required", "login-required"),
    ("passport", "passport"),
    ("captcha", "captcha"),
    ("verify_center", "verifycenter"),
    ("verification", "安全验证"),
    ("slider", "滑动验证"),
    ("operation_frequent", "操作频繁"),
    ("retry_later", "请稍后重试"),
    ("secsdk", "secsdk"),
    ("acrawler", "byted_acrawler"),
    ("ttwid", "ttwid"),
)


def final_url_kind(url: str) -> str:
    """只按路径返回目标类型，不保存主机、查询参数或完整地址。"""

    path = urlsplit(url).path.lower()
    if "/login" in path:
        return "login"
    if "/article/" in path:
        return "post"
    return "other"


def summarize_document_response(url: str, status: int) -> dict[str, Any]:
    """把主文档响应压缩为状态码和目标类型。"""

    return {"status": int(status), "target": final_url_kind(url)}


def cookie_name_shape(cookies: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """只记录 Cookie 数量及名称集合哈希，不记录名称明文和值。"""

    cookie_list = list(cookies)
    names = sorted({str(cookie.get("name", "")) for cookie in cookie_list if cookie.get("name")})
    encoded = "\n".join(names).encode("utf-8")
    return {
        "cookie_count": len(cookie_list),
        "cookie_name_set_sha256": hashlib.sha256(encoded).hexdigest(),
    }


def _text_length(document: str) -> int:
    without_scripts = re.sub(r"(?is)<(?:script|style)\b[^>]*>.*?</(?:script|style)>", " ", document)
    without_tags = re.sub(r"(?s)<[^>]+>", " ", without_scripts)
    return len(" ".join(html.unescape(without_tags).split()))


def build_access_diagnostic(
    *,
    candidate: str,
    trigger: str,
    sequence: int,
    attempt: int,
    input_url: str,
    final_url: str,
    http_status: int | None,
    response_class: str,
    document: str,
    cookies: list[Mapping[str, Any]],
    cookie_shape_available: bool,
    main_document_responses: list[dict[str, Any]],
) -> dict[str, Any]:
    """生成可判断登录、空壳页和挑战形态的脱敏证据。"""

    folded = document.casefold()
    title = re.search(r"(?is)<title\b[^>]*>(.*?)</title>", document)
    shape = cookie_name_shape(cookies)
    return {
        "schema_version": "1.0",
        "candidate": candidate,
        "trigger": trigger,
        "sequence": sequence,
        "attempt": attempt,
        "url_sha256": hashlib.sha256(input_url.encode("utf-8")).hexdigest(),
        "http_status": http_status,
        "response_class": response_class,
        "final_url_kind": final_url_kind(final_url),
        "final_url_matches_input": final_url == input_url,
        "document_length": len(document),
        "document_sha256": hashlib.sha256(document.encode("utf-8", errors="replace")).hexdigest(),
        "body_text_length": _text_length(document),
        "title_length": len(" ".join(html.unescape(title.group(1)).split())) if title else 0,
        "script_count": len(re.findall(r"(?i)<script\b", document)),
        "iframe_count": len(re.findall(r"(?i)<iframe\b", document)),
        "form_count": len(re.findall(r"(?i)<form\b", document)),
        "marker_hits": [name for name, marker in ACCESS_MARKERS if marker.casefold() in folded],
        "main_document_responses": main_document_responses[:10],
        "cookie_shape_available": cookie_shape_available,
        **shape,
    }
