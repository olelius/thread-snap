"""候选 A：使用 Scrapling 原生会话诊断重定向、会话连续性和网络链。"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Iterable
from pathlib import Path
from ipaddress import ip_address
from typing import Any
from urllib.parse import parse_qsl, urljoin, urlsplit

from scrapling.fetchers import DynamicSession, FetcherSession

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "poc" / "shared"))

from contract import classify_document, extract_input_post_id, url_sha256  # noqa: E402


def path_template(value: str | None, base_url: str | None = None) -> str | None:
    """仅保留占位化路径和查询键，避免诊断摘要包含完整 URL。"""

    if not value:
        return None
    absolute = urljoin(base_url or "https://TARGET/", value)
    parsed = urlsplit(absolute)
    path = re.sub(r"\d{6,}", "POST_ID", parsed.path)
    keys = sorted({key for key, _ in parse_qsl(parsed.query, keep_blank_values=True)})
    return f"{path}?keys={','.join(keys)}" if keys else path


def header_value(headers: Any, name: str) -> str | None:
    """兼容 Scrapling/curl_cffi 的响应头映射。"""

    if headers is None:
        return None
    for key, value in dict(headers).items():
        if str(key).lower() == name.lower():
            return str(value)
    return None


def response_chain(response: Any, input_url: str) -> list[dict[str, Any]]:
    """从静态响应及 history 生成主文档链。"""

    chain: list[dict[str, Any]] = []
    entries: Iterable[Any] = [*(getattr(response, "history", None) or []), response]
    for entry in entries:
        entry_url = str(getattr(entry, "url", input_url))
        chain.append(
            {
                "status": int(getattr(entry, "status", getattr(entry, "status_code", 0))),
                "path": path_template(entry_url),
                "location": path_template(header_value(getattr(entry, "headers", None), "location"), entry_url),
            }
        )
    return chain


def response_document(response: Any) -> str:
    """把响应体转换为文本。"""

    body = response.body
    if isinstance(body, bytes):
        return body.decode(getattr(response, "encoding", None) or "utf-8", errors="replace")
    return str(body)


def static_diagnostics(urls: list[str]) -> list[dict[str, Any]]:
    """分别记录禁止跳转和持久跟随跳转的 HTTP 结果。"""

    rows: list[dict[str, Any]] = []
    with FetcherSession(follow_redirects=False, retries=1, timeout=30, stealthy_headers=False) as session:
        for url in urls:
            response = session.get(url)
            document = response_document(response)
            rows.append(
                {
                    "candidate": "candidate-a",
                    "variant": "http-no-referer-no-follow",
                    "url_sha256": url_sha256(url),
                    "document_chain": response_chain(response, url),
                    "body_bytes": len(document.encode("utf-8")),
                    "jsvm_marker": "_$jsvmprt" in document,
                }
            )
    with FetcherSession(follow_redirects=False, retries=1, timeout=30) as session:
        for url in urls:
            response = session.get(url)
            document = response_document(response)
            rows.append(
                {
                    "candidate": "candidate-a",
                    "variant": "http-no-follow",
                    "url_sha256": url_sha256(url),
                    "document_chain": response_chain(response, url),
                    "body_bytes": len(document.encode("utf-8")),
                    "jsvm_marker": "_$jsvmprt" in document,
                }
            )
    with FetcherSession(follow_redirects="safe", retries=1, timeout=30) as session:
        for url in urls:
            response = session.get(url)
            document = response_document(response)
            classification = classify_document(str(response.url), int(response.status), document, extract_input_post_id(url))
            rows.append(
                {
                    "candidate": "candidate-a",
                    "variant": "http-persistent-follow",
                    "url_sha256": url_sha256(url),
                    "document_chain": response_chain(response, url),
                    "body_bytes": len(document.encode("utf-8")),
                    "jsvm_marker": "_$jsvmprt" in document,
                    "response_class": classification["response_class"],
                    "status": classification["status"],
                }
            )
    return rows


def browser_diagnostics(
    urls: list[str],
    output_dir: Path,
    browser_engine: str,
    direct_ip: str | None,
    profile_dir: Path | None,
) -> list[dict[str, Any]]:
    """在一个持久 DynamicSession 内执行首页预热、首访和同会话复访。"""

    rows: list[dict[str, Any]] = []
    profile = profile_dir or output_dir / "browser-profile"
    profile.mkdir(parents=True, exist_ok=True)
    active: dict[str, Any] = {
        "label": None,
        "documents": [],
        "subrequests": [],
        "cookie_count": 0,
        "cookie_name_hashes": [],
        "ua_headless": None,
    }

    def page_setup(page: Any) -> None:
        if getattr(page, "_threadsnap_diagnostic_listener", False):
            return

        def on_response(response: Any) -> None:
            if active["label"] is None:
                return
            resource_type = response.request.resource_type
            event = {"status": response.status, "path": path_template(response.url)}
            if resource_type == "document":
                event["location"] = path_template(response.headers.get("location"), response.url)
                active["documents"].append(event)
            elif resource_type in {"xhr", "fetch"}:
                active["subrequests"].append(event)

        page.on("response", on_response)
        setattr(page, "_threadsnap_diagnostic_listener", True)

    def page_action(page: Any) -> None:
        cookies = page.context.cookies()
        active["cookie_count"] = len(cookies)
        active["cookie_name_hashes"] = sorted(
            hashlib.sha256(cookie["name"].encode("utf-8")).hexdigest() for cookie in cookies
        )
        user_agent = page.evaluate("navigator.userAgent")
        active["ua_headless"] = "HeadlessChrome" in user_agent

    def fetch_and_record(session: Any, url: str, label: str) -> None:
        active.update(
            label=label,
            documents=[],
            subrequests=[],
            cookie_count=0,
            cookie_name_hashes=[],
            ua_headless=None,
        )
        response = session.fetch(
            url,
            google_search=False,
            page_setup=page_setup,
            page_action=page_action,
            wait=5_000,
            network_idle=False,
        )
        document = response_document(response)
        row: dict[str, Any] = {
            "candidate": "candidate-a",
            "variant": label,
            "url_sha256": url_sha256(url),
            "document_chain": active["documents"],
            "subrequest_statuses": summarize_subrequests(active["subrequests"]),
            "final_path": path_template(str(response.url)),
            "cookie_count": active["cookie_count"],
            "cookie_name_hashes": active["cookie_name_hashes"],
            "ua_headless": active["ua_headless"],
            "body_bytes": len(document.encode("utf-8")),
        }
        try:
            classification = classify_document(
                str(response.url), int(response.status), document, extract_input_post_id(url)
            )
            row.update(response_class=classification["response_class"], status=classification["status"])
        except ValueError:
            row.update(response_class="navigation", status="diagnostic")
        rows.append(row)

    variant_suffix = "-real-chrome" if browser_engine == "real-chrome" else ""
    extra_flags: list[str] = []
    if direct_ip:
        host = urlsplit(urls[0]).hostname
        extra_flags = ["--no-proxy-server", f"--host-resolver-rules=MAP {host} {direct_ip}"]
        variant_suffix += "-direct"
    with DynamicSession(
        headless=True,
        timeout=45_000,
        retries=1,
        max_pages=1,
        user_data_dir=str(profile),
        real_chrome=browser_engine == "real-chrome",
        extra_flags=extra_flags,
    ) as session:
        origin = f"{urlsplit(urls[0]).scheme}://{urlsplit(urls[0]).netloc}/"
        fetch_and_record(session, origin, f"browser-home-warmup{variant_suffix}")
        for url in urls:
            fetch_and_record(session, url, f"browser-persistent-first{variant_suffix}")
        fetch_and_record(session, urls[0], f"browser-persistent-revisit{variant_suffix}")
    return rows


def summarize_subrequests(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按状态和路径模板聚合 XHR/fetch，避免保存查询值或请求内容。"""

    counts: dict[tuple[int, str | None], int] = {}
    for event in events:
        key = (event["status"], event["path"])
        counts[key] = counts.get(key, 0) + 1
    return [
        {"status": status, "path": path, "count": count}
        for (status, path), count in sorted(counts.items(), key=lambda item: (item[0][0], item[0][1] or ""))
    ]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    """使用 UTF-8/LF 写出诊断结果。"""

    payload = "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows)
    path.write_bytes(payload.encode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--browser-engine", choices=("bundled", "real-chrome"), default="bundled")
    parser.add_argument("--direct-ip")
    parser.add_argument("--profile-dir", type=Path)
    args = parser.parse_args()
    urls = [line.strip() for line in args.input.read_text("utf-8-sig").splitlines() if line.strip()]
    if args.limit < 1 or args.limit > len(urls):
        raise ValueError("limit 超出输入清单范围")
    urls = urls[: args.limit]
    if args.direct_ip:
        ip_address(args.direct_ip)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    rows = [
        *static_diagnostics(urls),
        *browser_diagnostics(urls, args.output_dir, args.browser_engine, args.direct_ip, args.profile_dir),
    ]
    write_jsonl(args.output_dir / "diagnostics.jsonl", rows)
    print(json.dumps({"candidate": "candidate-a", "rows": len(rows)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
