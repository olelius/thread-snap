"""认证 HTTP 会话交接与诊断测试。"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SHARED = ROOT / "poc" / "shared"
SOURCE = ROOT / "poc" / "candidate-a" / "src"
sys.path[:0] = [str(SHARED), str(SOURCE)]

from session_handoff import load_http_cookies  # noqa: E402

MODULE_PATH = SOURCE / "authenticated_http_probe.py"
SPEC = importlib.util.spec_from_file_location("candidate_a_authenticated_http_probe", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class SessionHandoffTests(unittest.TestCase):
    def test_filters_domain_and_expired_cookies_without_exposing_values(self) -> None:
        secret = "SECRET_COOKIE_VALUE"
        state = {
            "cookies": [
                {"name": "session", "value": secret, "domain": ".target.test", "path": "/", "secure": True},
                {"name": "other", "value": "OTHER_SECRET", "domain": ".elsewhere.test", "path": "/"},
                {
                    "name": "expired",
                    "value": "OLD_SECRET",
                    "domain": ".target.test",
                    "path": "/",
                    "expires": time.time() - 10,
                },
            ]
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "storage-state.json"
            path.write_text(json.dumps(state), encoding="utf-8")
            jar, metadata = load_http_cookies(path, "https://www.target.test/ugc/article/123")
        self.assertEqual(1, metadata["accepted_cookie_count"])
        self.assertEqual(1, metadata["unrelated_cookie_count"])
        self.assertEqual(1, metadata["expired_cookie_count"])
        self.assertNotIn(secret, json.dumps(metadata))
        self.assertNotIn("session", json.dumps(metadata))
        self.assertIsNotNone(jar)

    def test_rejects_state_without_target_cookies(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "storage-state.json"
            path.write_text('{"cookies": []}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "没有适用于目标域"):
                load_http_cookies(path, "https://target.test/post/1")


class RiskAnalysisTests(unittest.TestCase):
    def test_login_is_reported_as_rejected_or_incomplete_session(self) -> None:
        summary = {"success_count": 0, "result_count": 1, "response_class_counts": {"login": 1}}
        metadata = {
            "source_cookie_count": 4,
            "accepted_cookie_count": 3,
            "expired_cookie_count": 0,
            "unrelated_cookie_count": 1,
            "malformed_cookie_count": 0,
        }
        analysis = MODULE.infer_risk(summary, metadata)
        self.assertEqual("session_rejected_or_incomplete", analysis["category"])

    def test_all_failures_as_404_are_not_reported_as_risk_control(self) -> None:
        summary = {
            "success_count": 399,
            "result_count": 500,
            "response_class_counts": {"post": 399, "error": 101},
            "http_status_counts": {"200": 399, "404": 101},
        }
        metadata = {
            "source_cookie_count": 4,
            "accepted_cookie_count": 3,
            "expired_cookie_count": 0,
            "unrelated_cookie_count": 1,
            "malformed_cookie_count": 0,
        }
        analysis = MODULE.infer_risk(summary, metadata)
        self.assertEqual("input_not_found", analysis["category"])


if __name__ == "__main__":
    unittest.main()
