"""在浏览器存储状态与纯 HTTP 会话之间传递 Cookie。

本模块只在内存中处理 Cookie 值；调用方只应持久化统计信息，不能输出名称或值。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from curl_cffi.requests import Cookies


def _domain_matches(hostname: str, cookie_domain: str) -> bool:
    """判断 Cookie 域是否适用于目标主机。"""

    domain = cookie_domain.lstrip(".").lower()
    host = hostname.lower()
    return bool(domain) and (host == domain or host.endswith(f".{domain}"))


def load_http_cookies(storage_state_path: Path, target_url: str) -> tuple[Cookies, dict[str, Any]]:
    """读取 Playwright storage state，构造限定到目标域的 HTTP Cookie 容器。

    返回的元数据刻意不包含 Cookie 名称、值或完整目标 URL。
    """

    hostname = (urlsplit(target_url).hostname or "").lower()
    if not hostname:
        raise ValueError("目标 URL 缺少有效主机名")
    if not storage_state_path.is_file():
        raise FileNotFoundError(f"浏览器状态文件不存在: {storage_state_path}")

    state = json.loads(storage_state_path.read_text(encoding="utf-8"))
    raw_cookies = state.get("cookies") if isinstance(state, dict) else None
    if not isinstance(raw_cookies, list):
        raise ValueError("storage-state.json 缺少 cookies 数组")

    now = time.time()
    jar = Cookies()
    accepted = 0
    expired = 0
    unrelated = 0
    malformed = 0
    secure_count = 0
    for item in raw_cookies:
        if not isinstance(item, dict):
            malformed += 1
            continue
        name = item.get("name")
        value = item.get("value")
        domain = item.get("domain")
        path = item.get("path", "/")
        expires = item.get("expires", -1)
        if not all(isinstance(part, str) and part for part in (name, value, domain, path)):
            malformed += 1
            continue
        if not _domain_matches(hostname, domain):
            unrelated += 1
            continue
        if isinstance(expires, (int, float)) and expires > 0 and expires <= now:
            expired += 1
            continue
        secure = bool(item.get("secure", False))
        jar.set(name, value, domain=domain, path=path, secure=secure)
        accepted += 1
        secure_count += int(secure)

    if accepted == 0:
        raise ValueError("浏览器状态中没有适用于目标域的有效 Cookie")
    return jar, {
        "source_cookie_count": len(raw_cookies),
        "accepted_cookie_count": accepted,
        "secure_cookie_count": secure_count,
        "expired_cookie_count": expired,
        "unrelated_cookie_count": unrelated,
        "malformed_cookie_count": malformed,
        "target_host": hostname,
    }
