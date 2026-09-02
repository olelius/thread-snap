"""腾讯滑块验证码的普通 HTTP 编排器。"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlencode, urljoin

from .image import analyze_slider_offset
from .tdc import TdcRuntime, TdcRuntimeError

logger = logging.getLogger(__name__)

PREHANDLE_URL = "https://t.captcha.qq.com/cap_union_prehandle"
VERIFY_URL = "https://t.captcha.qq.com/cap_union_new_verify"
CAPTCHA_ORIGIN = "https://captcha.gtimg.com"
CAPTCHA_TEMPLATE = f"{CAPTCHA_ORIGIN}/static/template/drag_ele.f15e4d0f.html"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/151.0.0.0 Safari/537.36"
)


class HttpTransport(Protocol):
    """解题器需要的最小 HTTP 能力，由调用平台提供会话。"""

    def get(self, url: str, **kwargs: Any) -> Any: ...

    def post(self, url: str, **kwargs: Any) -> Any: ...


class TencentCaptchaSolverProtocol(Protocol):
    """供不同平台适配器调用的稳定解题合同。"""

    def solve(self, *, entry_url: str, transport: HttpTransport) -> "TencentCaptchaResult": ...


class TencentCaptchaError(RuntimeError):
    """腾讯协议链的稳定错误，不携带票据或请求正文。"""

    def __init__(self, code: str, message: str, *, stage: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.stage = stage


@dataclass(frozen=True)
class TencentCaptchaResult:
    """一次性验证结果；票据仅交给当次平台回调。"""

    ticket: str
    randstr: str
    elapsed_seconds: float
    network_request_count: int
    opcode_count: int
    handler_count: int
    confidence_margin: float


class ProtocolCircuitBreaker:
    """在进程内抑制已知漂移或连续失败造成的重复请求。"""

    def __init__(self, *, failure_threshold: int = 2, cooldown_seconds: float = 900.0) -> None:
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._lock = threading.Lock()
        self._failures = 0
        self._opened_until = 0.0

    def before_attempt(self) -> None:
        with self._lock:
            if time.monotonic() < self._opened_until:
                raise TencentCaptchaError(
                    "TENCENT_CAPTCHA_CIRCUIT_OPEN",
                    "腾讯验证码协议熔断仍在冷却。",
                    stage="circuit",
                )

    def success(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_until = 0.0

    def failure(self, *, drift: bool) -> None:
        with self._lock:
            self._failures += 1
            if drift or self._failures >= self.failure_threshold:
                self._opened_until = time.monotonic() + self.cooldown_seconds


_CIRCUIT_BREAKERS: dict[str, ProtocolCircuitBreaker] = {}
_CIRCUIT_BREAKERS_LOCK = threading.Lock()


def _circuit_breaker_for(app_id: str) -> ProtocolCircuitBreaker:
    """按AppId共享熔断状态，避免一个平台影响不同腾讯接入。"""

    with _CIRCUIT_BREAKERS_LOCK:
        return _CIRCUIT_BREAKERS.setdefault(app_id, ProtocolCircuitBreaker())


def _parse_json_or_jsonp(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        match = re.match(r"^[^(]+\((.*)\)\s*;?\s*$", text, re.DOTALL)
        if not match:
            raise ValueError("响应不是 JSON 或 JSONP。") from None
        value = json.loads(match.group(1))
    if not isinstance(value, dict):
        raise ValueError("响应顶层结构不是对象。")
    return value


class TencentCaptchaSolver:
    """复用逆向结果，为调用平台处理每次动态 challenge。"""

    def __init__(
        self,
        *,
        app_id: str,
        timeout_seconds: float = 20.0,
        minimum_confidence_margin: float = 1.0,
        max_pow_counter: int = 20_000_000,
        runtime: TdcRuntime | None = None,
        circuit_breaker: ProtocolCircuitBreaker | None = None,
    ) -> None:
        if not app_id.strip():
            raise ValueError("腾讯验证码 AppId 为空。")
        self.app_id = app_id.strip()
        self.timeout_seconds = timeout_seconds
        self.minimum_confidence_margin = minimum_confidence_margin
        self.max_pow_counter = max_pow_counter
        self.runtime = runtime or TdcRuntime(timeout_seconds=min(15.0, timeout_seconds))
        self.circuit_breaker = circuit_breaker or _circuit_breaker_for(self.app_id)

    def _request_get(
        self, transport: HttpTransport, url: str, *, headers: dict[str, str]
    ) -> Any:
        try:
            response = transport.get(
                url,
                headers={"User-Agent": USER_AGENT, **headers},
                timeout=self.timeout_seconds,
                allow_redirects=True,
            )
        except Exception as exc:
            raise TencentCaptchaError(
                "TENCENT_CAPTCHA_NETWORK_ERROR",
                "腾讯验证码资源请求失败。",
                stage="download",
            ) from exc
        if int(response.status_code) != 200:
            raise TencentCaptchaError(
                "TENCENT_CAPTCHA_HTTP_ERROR",
                f"腾讯验证码资源返回 HTTP {response.status_code}。",
                stage="download",
            )
        return response

    def solve(self, *, entry_url: str, transport: HttpTransport) -> TencentCaptchaResult:
        started = time.perf_counter()
        request_count = 0
        self.circuit_breaker.before_attempt()
        try:
            callback = f"_aq_{secrets.randbelow(900000) + 100000}"
            params = {
                "aid": self.app_id,
                "protocol": "https",
                "accver": "1",
                "showtype": "popup",
                "ua": base64.b64encode(USER_AGENT.encode()).decode().rstrip("="),
                "noheader": "1",
                "fb": "1",
                "aged": "0",
                "enableAged": "0",
                "enableDarkMode": "0",
                "grayscale": "1",
                "dyeid": "0",
                "clientype": "2",
                "cap_cd": "",
                "uid": "",
                "lang": "zh-cn",
                "entry_url": entry_url,
                "elder_captcha": "0",
                "js": "/tcaptcha-frame.c67d254a.js",
                "login_appid": "",
                "support_media": "jpeg,png,gif,webp,mp4,webm",
                "wb": "1",
                "version": "1.1.0",
                "subsid": "1",
                "callback": callback,
                "sess": "",
                "agent_id": "",
                "agent_auth_sign": "",
            }
            response = self._request_get(
                transport,
                f"{PREHANDLE_URL}?{urlencode(params)}",
                headers={"Referer": entry_url, "Accept": "*/*"},
            )
            request_count += 1
            try:
                prehandle = _parse_json_or_jsonp(response.text)
                data = prehandle["data"]
                dyn = data["dyn_show_info"]
                cfg = data["comm_captcha_cfg"]
                background_cfg = dyn["bg_elem_cfg"]
                piece = next(item for item in dyn["fg_elem_list"] if item.get("id") == 1)
                sess = str(prehandle["sess"])
                background_url = urljoin("https://t.captcha.qq.com", background_cfg["img_url"])
                sprite_url = urljoin("https://t.captcha.qq.com", dyn["sprite_url"])
                tdc_url = urljoin("https://t.captcha.qq.com", cfg["tdc_path"])
                pow_cfg = cfg["pow_cfg"]
                pow_prefix = str(pow_cfg["prefix"])
                pow_target = str(pow_cfg["md5"])
                background_size = background_cfg["size_2d"]
                sprite_pos = piece["sprite_pos"]
                initial_pos = piece["init_pos"]
            except (KeyError, TypeError, StopIteration, ValueError) as exc:
                raise TencentCaptchaError(
                    "TENCENT_CAPTCHA_PREHANDLE_DRIFT",
                    "腾讯验证码 prehandle 结构发生变化。",
                    stage="prehandle",
                ) from exc
            if prehandle.get("state") != 1 or not sess:
                raise TencentCaptchaError(
                    "TENCENT_CAPTCHA_PREHANDLE_REJECTED",
                    "腾讯验证码 prehandle 没有返回有效 challenge。",
                    stage="prehandle",
                )
            if (
                not isinstance(background_size, (list, tuple))
                or len(background_size) != 2
                or not re.fullmatch(r"[0-9a-fA-F]{32}", pow_target)
            ):
                raise TencentCaptchaError(
                    "TENCENT_CAPTCHA_PREHANDLE_DRIFT",
                    "腾讯验证码图片或 PoW 参数结构发生变化。",
                    stage="prehandle",
                )

            background_response = self._request_get(
                transport, background_url, headers={"Referer": CAPTCHA_ORIGIN + "/"}
            )
            sprite_response = self._request_get(
                transport, sprite_url, headers={"Referer": CAPTCHA_ORIGIN + "/"}
            )
            request_count += 2
            try:
                display_width = 340.0
                scale = display_width / float(background_size[0])
                offset = analyze_slider_offset(
                    bytes(background_response.content),
                    bytes(sprite_response.content),
                    display_width=display_width,
                    piece_top_css=float(initial_pos[1]) * scale,
                    piece_left_css=float(initial_pos[0]) * scale,
                    piece_sprite_x=int(sprite_pos[0]),
                    piece_sprite_y=int(sprite_pos[1]),
                )
            except (OSError, ValueError, IndexError, TypeError) as exc:
                raise TencentCaptchaError(
                    "TENCENT_CAPTCHA_IMAGE_DRIFT",
                    "腾讯验证码双图结构或几何发生变化。",
                    stage="image",
                ) from exc
            if offset.confidence_margin < self.minimum_confidence_margin:
                raise TencentCaptchaError(
                    "TENCENT_CAPTCHA_IMAGE_CONFIDENCE_LOW",
                    "腾讯验证码缺口识别置信度低，本次 challenge 已停止。",
                    stage="image",
                )

            prefix = pow_prefix
            target = pow_target.lower()
            pow_started = time.perf_counter()
            pow_counter = 0
            while pow_counter <= self.max_pow_counter:
                candidate = f"{prefix}{pow_counter}"
                if hashlib.md5(candidate.encode()).hexdigest() == target:
                    break
                pow_counter += 1
            else:
                raise TencentCaptchaError(
                    "TENCENT_CAPTCHA_POW_BOUND_EXCEEDED",
                    "腾讯验证码 PoW 超出本地计算上限。",
                    stage="pow",
                )
            pow_time_ms = max(1, round((time.perf_counter() - pow_started) * 1000))

            tdc_response = self._request_get(
                transport,
                tdc_url,
                headers={"Referer": CAPTCHA_TEMPLATE, "Accept": "*/*"},
            )
            request_count += 1
            try:
                runtime = self.runtime.evaluate(
                    bytes(tdc_response.content),
                    drag_css_px=offset.drag_css_px,
                    entry_url=entry_url,
                )
            except TdcRuntimeError as exc:
                raise TencentCaptchaError(
                    "TENCENT_CAPTCHA_TDC_DRIFT",
                    str(exc),
                    stage="tdc",
                ) from exc

            answer = json.dumps(
                [
                    {
                        "elem_id": 1,
                        "type": "DynAnswerType_POS",
                        "data": f"{offset.source_x},{offset.source_y}",
                    }
                ],
                ensure_ascii=False,
                separators=(",", ":"),
            )
            verify_form = {
                "collect": runtime.collect,
                "tlg": str(len(runtime.collect)),
                "eks": runtime.eks,
                "sess": sess,
                "ans": answer,
                "pow_answer": f"{prefix}{pow_counter}",
                "pow_calc_time": str(pow_time_ms),
            }
            try:
                verify_response = transport.post(
                    VERIFY_URL,
                    data=verify_form,
                    timeout=self.timeout_seconds,
                    allow_redirects=True,
                    headers={
                        "User-Agent": USER_AGENT,
                        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                        "Origin": CAPTCHA_ORIGIN,
                        "Referer": CAPTCHA_TEMPLATE,
                        "Accept": "*/*",
                    },
                )
            except Exception as exc:
                raise TencentCaptchaError(
                    "TENCENT_CAPTCHA_NETWORK_ERROR",
                    "腾讯验证码 verify 请求失败。",
                    stage="verify",
                ) from exc
            request_count += 1
            if int(verify_response.status_code) != 200:
                raise TencentCaptchaError(
                    "TENCENT_CAPTCHA_VERIFY_HTTP_ERROR",
                    f"腾讯验证码 verify 返回 HTTP {verify_response.status_code}。",
                    stage="verify",
                )
            try:
                verify = _parse_json_or_jsonp(verify_response.text)
            except (ValueError, json.JSONDecodeError) as exc:
                raise TencentCaptchaError(
                    "TENCENT_CAPTCHA_VERIFY_DRIFT",
                    "腾讯验证码 verify 响应结构发生变化。",
                    stage="verify",
                ) from exc
            error_code = (
                verify["errorCode"] if "errorCode" in verify else verify.get("error_code")
            )
            ticket = verify.get("ticket")
            randstr = verify.get("randstr")
            if (
                str(error_code) != "0"
                or not isinstance(ticket, str)
                or not ticket
                or not isinstance(randstr, str)
                or not randstr
            ):
                raise TencentCaptchaError(
                    "TENCENT_CAPTCHA_VERIFY_REJECTED",
                    "腾讯验证码 verify 业务校验未通过。",
                    stage="verify",
                )
            self.circuit_breaker.success()
            elapsed = time.perf_counter() - started
            logger.info(
                "腾讯验证码纯协议求解成功：requests=%s elapsed=%.3fs opcodes=%s handlers=%s",
                request_count,
                elapsed,
                runtime.opcode_count,
                runtime.handler_count,
            )
            return TencentCaptchaResult(
                ticket=ticket,
                randstr=randstr,
                elapsed_seconds=elapsed,
                network_request_count=request_count,
                opcode_count=runtime.opcode_count,
                handler_count=runtime.handler_count,
                confidence_margin=offset.confidence_margin,
            )
        except TencentCaptchaError as exc:
            drift = exc.code in {
                "TENCENT_CAPTCHA_PREHANDLE_DRIFT",
                "TENCENT_CAPTCHA_IMAGE_DRIFT",
                "TENCENT_CAPTCHA_TDC_DRIFT",
                "TENCENT_CAPTCHA_VERIFY_DRIFT",
            }
            self.circuit_breaker.failure(drift=drift)
            logger.warning("腾讯验证码纯协议求解停止：stage=%s code=%s", exc.stage, exc.code)
            raise
