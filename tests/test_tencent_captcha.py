"""平台无关腾讯验证码组件与易车回调合同。"""

from __future__ import annotations

import hashlib
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from threadsnap.collectors.yiche_waf import (
    YicheWafCallbackError,
    parse_waf_seqid,
    submit_yiche_waf_callback,
)
from threadsnap.tencent_captcha import (
    TencentCaptchaError,
    TencentCaptchaResult,
    TencentCaptchaSolver,
)
from threadsnap.tencent_captcha.image import SliderOffset
from threadsnap.tencent_captcha.solver import ProtocolCircuitBreaker
from threadsnap.tencent_captcha.tdc import TdcRuntime, TdcRuntimeResult


class FakeRuntime:
    """隔离 Node 边界，验证 Python 编排和动态材料传递。"""

    def __init__(self) -> None:
        self.calls: list[tuple[bytes, float, str]] = []

    def evaluate(self, source: bytes, *, drag_css_px: float, entry_url: str) -> TdcRuntimeResult:
        self.calls.append((source, drag_css_px, entry_url))
        return TdcRuntimeResult("collect-fixture", "eks-fixture", 94, 74)


class FakeTransport:
    """按腾讯五请求协议返回脱敏 fixture。"""

    def __init__(self) -> None:
        prefix = "fixture#"
        target = hashlib.md5(f"{prefix}2".encode()).hexdigest()
        prehandle = {
            "state": 1,
            "sess": "sess-fixture",
            "data": {
                "dyn_show_info": {
                    "bg_elem_cfg": {
                        "size_2d": [672, 480],
                        "img_url": "/background",
                    },
                    "sprite_url": "/sprite",
                    "fg_elem_list": [
                        {
                            "id": 1,
                            "sprite_pos": [140, 490],
                            "init_pos": [50, 136],
                        }
                    ],
                },
                "comm_captcha_cfg": {
                    "tdc_path": "/tdc.js?fixture=1",
                    "pow_cfg": {"prefix": prefix, "md5": target},
                },
            },
        }
        self.responses = {
            "prehandle": SimpleNamespace(
                status_code=200,
                text=f"callback({json.dumps(prehandle)})",
                content=b"",
            ),
            "background": SimpleNamespace(status_code=200, text="", content=b"background"),
            "sprite": SimpleNamespace(status_code=200, text="", content=b"sprite"),
            "tdc": SimpleNamespace(status_code=200, text="", content=b"tdc-source"),
        }
        self.calls: list[tuple[str, str, dict]] = []

    def get(self, url: str, **kwargs):
        self.calls.append(("GET", url, kwargs))
        if "cap_union_prehandle" in url:
            return self.responses["prehandle"]
        if url.endswith("/background"):
            return self.responses["background"]
        if url.endswith("/sprite"):
            return self.responses["sprite"]
        return self.responses["tdc"]

    def post(self, url: str, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return SimpleNamespace(
            status_code=200,
            text=json.dumps({"errorCode": 0, "ticket": "ticket-fixture", "randstr": "R4nd"}),
            content=b"",
        )


class TencentCaptchaSolverTests(unittest.TestCase):
    def test_prebuilt_tdc_runtime_assets_are_installed(self) -> None:
        runtime = TdcRuntime()
        self.assertTrue(all(path.is_file() for path in runtime.required_asset_paths()))

    def test_solver_reuses_protocol_and_recomputes_dynamic_challenge(self) -> None:
        transport = FakeTransport()
        runtime = FakeRuntime()
        breaker = ProtocolCircuitBreaker(cooldown_seconds=0.01)
        solver = TencentCaptchaSolver(
            app_id="fixture-app", runtime=runtime, circuit_breaker=breaker
        )
        offset = SliderOffset(358, 136, 155.833, 4.7, "strongest-outline")
        with patch(
            "threadsnap.tencent_captcha.solver.analyze_slider_offset", return_value=offset
        ):
            result = solver.solve(
                entry_url="https://target.example/thread-1.html", transport=transport
            )

        self.assertEqual(("ticket-fixture", "R4nd"), (result.ticket, result.randstr))
        self.assertEqual((5, 94, 74), (result.network_request_count, result.opcode_count, result.handler_count))
        self.assertEqual([(b"tdc-source", 155.833, "https://target.example/thread-1.html")], runtime.calls)
        verify_call = transport.calls[-1]
        self.assertEqual("POST", verify_call[0])
        self.assertEqual("fixture#2", verify_call[2]["data"]["pow_answer"])
        self.assertEqual("sess-fixture", verify_call[2]["data"]["sess"])
        self.assertNotIn("ticket-fixture", repr(transport.calls[:-1]))
        self.assertIn("aid=fixture-app", transport.calls[0][1])

    def test_structural_drift_opens_process_circuit(self) -> None:
        breaker = ProtocolCircuitBreaker(cooldown_seconds=60)
        breaker.failure(drift=True)
        with self.assertRaises(TencentCaptchaError) as caught:
            breaker.before_attempt()
        self.assertEqual("TENCENT_CAPTCHA_CIRCUIT_OPEN", caught.exception.code)


class YicheWafCallbackTests(unittest.TestCase):
    def test_seqid_parser_is_strict(self) -> None:
        self.assertEqual(
            "fixture__captcha",
            parse_waf_seqid(b'<script>var seqid = "fixture__captcha";</script>'),
        )
        with self.assertRaises(YicheWafCallbackError):
            parse_waf_seqid(b"<script>var token='fixture';</script>")

    def test_callback_uses_same_transport_and_four_line_body(self) -> None:
        result = TencentCaptchaResult("ticket", "rand", 0.1, 5, 94, 74, 4.0)

        class Solver:
            def solve(self, *, entry_url: str, transport):
                self.call = (entry_url, transport)
                return result

        class Transport:
            def post(self, url: str, **kwargs):
                self.call = (url, kwargs)
                return SimpleNamespace(status_code=200)

        solver = Solver()
        transport = Transport()
        actual = submit_yiche_waf_callback(
            content=b'<script>var seqid="seq__captcha";</script>',
            entry_url="https://target.example/thread-1.html",
            transport=transport,
            solver=solver,
            timeout_seconds=20,
        )
        self.assertIs(result, actual)
        self.assertIs(transport, solver.call[1])
        self.assertEqual("https://target.example/WafCaptcha", transport.call[0])
        self.assertEqual("0\nticket\nrand\nseq__captcha", transport.call[1]["data"])


if __name__ == "__main__":
    unittest.main()
