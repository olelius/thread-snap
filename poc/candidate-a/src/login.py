"""候选 A：使用 Scrapling DynamicSession 建立持久登录会话。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from scrapling.fetchers import DynamicSession

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "poc" / "shared"))

from contract import classify_document, extract_input_post_id  # noqa: E402


def path_template(url: str) -> str:
    """只保留占位化路径和查询键。"""

    parsed = urlsplit(url)
    path = re.sub(r"\d{6,}", "POST_ID", parsed.path)
    keys = sorted({key for key, _ in parse_qsl(parsed.query, keep_blank_values=True)})
    return f"{path}?keys={','.join(keys)}" if keys else path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe-url", required=True)
    parser.add_argument("--profile-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()

    account = os.environ.get("THREADSNAP_PLATFORM_ACCOUNT")
    password = os.environ.get("THREADSNAP_PLATFORM_PASSWORD")
    if not account or not password:
        raise RuntimeError("缺少登录凭证环境变量")
    os.environ.pop("THREADSNAP_PLATFORM_ACCOUNT", None)
    os.environ.pop("THREADSNAP_PLATFORM_PASSWORD", None)

    state: dict[str, Any] = {"documents": [], "subrequests": [], "submitted": False}

    def page_setup(page: Any) -> None:
        def on_response(response: Any) -> None:
            resource_type = response.request.resource_type
            event = {"status": response.status, "path": path_template(response.url)}
            if resource_type == "document":
                state["documents"].append(event)
            elif resource_type in {"xhr", "fetch"}:
                state["subrequests"].append(event)

        page.on("response", on_response)

    def page_action(page: Any) -> None:
        page.wait_for_timeout(2_000)
        if "/login-required" in page.url:
            if page.locator('input[name="code"]').count():
                page.locator("button").last.click(timeout=5_000)
                page.wait_for_timeout(500)
            page.locator('input[name="account"]').fill(account)
            page.locator('input[name="password"]').fill(password)
            page.get_by_role("button", name="登录", exact=True).click(timeout=10_000)
            state["submitted"] = True
            page.wait_for_timeout(10_000)
        state["final_url"] = page.url
        state["document"] = page.content()
        cookies = page.context.cookies()
        state["cookie_count"] = len(cookies)
        state["cookie_name_hashes"] = sorted(
            hashlib.sha256(cookie["name"].encode("utf-8")).hexdigest() for cookie in cookies
        )
        state["verification_required"] = any(
            marker in state["document"].lower() for marker in ("captcha", "验证码", "验证中心")
        )

    args.profile_dir.mkdir(parents=True, exist_ok=True)
    with DynamicSession(
        headless=args.headless,
        real_chrome=True,
        google_search=False,
        max_pages=1,
        timeout=60_000,
        retries=1,
        user_data_dir=str(args.profile_dir.resolve()),
    ) as session:
        session.fetch(
            args.probe_url,
            page_setup=page_setup,
            page_action=page_action,
            wait=1_000,
            network_idle=False,
        )

    final_url = str(state.get("final_url", args.probe_url))
    document = str(state.pop("document", ""))
    classification = classify_document(final_url, 200, document, extract_input_post_id(args.probe_url))
    result = {
        "schema_version": "1.0",
        "candidate": "candidate-a",
        "submitted": state["submitted"],
        "logged_in": "/login-required" not in final_url and classification["response_class"] == "post",
        "final_path": path_template(final_url),
        "response_class": classification["response_class"],
        "status": classification["status"],
        "cookie_count": state.get("cookie_count", 0),
        "cookie_name_hashes": state.get("cookie_name_hashes", []),
        "verification_required": state.get("verification_required", False),
        "document_chain": state["documents"],
        "subrequest_statuses": sorted({event["status"] for event in state["subrequests"]}),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "cookie_name_hashes"}, ensure_ascii=False))
    return 0 if result["logged_in"] else 4


if __name__ == "__main__":
    raise SystemExit(main())
