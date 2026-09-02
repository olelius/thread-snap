"""易车对腾讯验证码结果的站点专属回调。"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

from ..tencent_captcha import TencentCaptchaResult, TencentCaptchaSolverProtocol

SEQID_RE = re.compile(rb'var\s+seqid\s*=\s*["\']([^"\']+__captcha)["\']')


class YicheWafCallbackError(RuntimeError):
    """易车 WAF 页面或回调门发生变化。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def parse_waf_seqid(content: bytes | str) -> str:
    """从当前易车 WAF 文档提取只属于本轮的 seqid。"""

    raw = content.encode("utf-8") if isinstance(content, str) else content
    match = SEQID_RE.search(raw)
    if not match:
        raise YicheWafCallbackError(
            "YICHE_WAF_SEQID_DRIFT", "易车验证码页面的 seqid 结构发生变化。"
        )
    try:
        return match.group(1).decode("ascii")
    except UnicodeDecodeError as exc:
        raise YicheWafCallbackError(
            "YICHE_WAF_SEQID_DRIFT", "易车验证码页面返回了异常 seqid。"
        ) from exc


def submit_yiche_waf_callback(
    *,
    content: bytes | str,
    entry_url: str,
    transport: Any,
    solver: TencentCaptchaSolverProtocol,
    timeout_seconds: float,
) -> TencentCaptchaResult:
    """求解全新 challenge，并把一次性票据提交到易车当前 WAF 会话。"""

    seqid = parse_waf_seqid(content)
    result = solver.solve(entry_url=entry_url, transport=transport)
    parsed = urlsplit(entry_url)
    endpoint = f"{parsed.scheme}://{parsed.netloc}/WafCaptcha"
    try:
        response = transport.post(
            endpoint,
            data=f"0\n{result.ticket}\n{result.randstr}\n{seqid}",
            timeout=timeout_seconds,
            allow_redirects=True,
            headers={
                "Content-Type": "text/plain;charset=UTF-8",
                "Origin": f"{parsed.scheme}://{parsed.netloc}",
                "Referer": entry_url,
            },
        )
    except Exception as exc:
        raise YicheWafCallbackError(
            "YICHE_WAF_POST_NETWORK_ERROR", "易车验证码回调请求失败。"
        ) from exc
    if int(response.status_code) != 200:
        raise YicheWafCallbackError(
            "YICHE_WAF_POST_REJECTED",
            f"易车验证码回调返回 HTTP {response.status_code}。",
        )
    return result
