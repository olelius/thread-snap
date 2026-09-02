"""Scrapling 统一传输层的本地、确定性合同测试。"""

from __future__ import annotations

import json
import logging
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from threadsnap.collectors.autohome import AutohomeCollector
from threadsnap.collectors.dongchedi import DongchediCollector
from threadsnap.collectors.yiche import YicheCollector
from threadsnap.reputation_dongchedi import DongchediReputationAdapter
from threadsnap.scrapling_transport import (
    BrowserCookieStore,
    BrowserResourceBudget,
    ExecutionScopeKey,
    ScraplingHttpPool,
)


class _Handler(BaseHTTPRequestHandler):
    request_counts: dict[str, int] = {}

    def do_GET(self) -> None:  # noqa: N802 - 标准库回调名称固定。
        self.request_counts[self.path] = self.request_counts.get(self.path, 0) + 1
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/json")
            self.end_headers()
            return
        if self.path == "/set-cookie":
            self.send_response(200)
            self.send_header("Set-Cookie", "server_cookie=kept; Path=/")
            self.end_headers()
            self.wfile.write(b"ok")
            return
        if self.path == "/echo-cookie":
            payload = json.dumps(
                {"cookie": self.headers.get("Cookie", "")}, ensure_ascii=False
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(payload)
            return
        if self.path == "/error":
            self.send_response(503)
            self.end_headers()
            self.wfile.write(b"retry is owned by collector")
            return
        payload = json.dumps({"message": "中文响应"}, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, _format: str, *args: object) -> None:
        del args


class ScraplingTransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _Handler.request_counts = {}
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)

    def test_response_adapter_preserves_existing_collector_contract(self) -> None:
        pool = ScraplingHttpPool(None, timeout_seconds=5)
        try:
            response = pool.session().get(f"{self.base_url}/redirect")
            self.assertEqual(response.status_code, 200)
            self.assertIn("中文响应", response.text)
            self.assertEqual(response.json(), {"message": "中文响应"})
            self.assertEqual(response.content, response.text.encode("utf-8"))
            self.assertEqual(str(response.url), f"{self.base_url}/json")
            self.assertEqual(len(response.history), 1)
        finally:
            pool.close()

    def test_browser_and_server_cookies_share_one_scrapling_session(self) -> None:
        state = {
            "cookies": [
                {
                    "name": "browser_cookie",
                    "value": "imported",
                    "domain": "127.0.0.1",
                    "path": "/",
                    "secure": False,
                    "expires": time.time() + 60,
                }
            ]
        }
        pool = ScraplingHttpPool(state, timeout_seconds=5)
        try:
            session = pool.session()
            session.get(f"{self.base_url}/set-cookie")
            echoed = session.get(f"{self.base_url}/echo-cookie").json()["cookie"]
            self.assertIn("browser_cookie=imported", echoed)
            self.assertIn("server_cookie=kept", echoed)
        finally:
            pool.close()

    def test_server_cookie_is_shared_with_another_http_thread(self) -> None:
        pool = ScraplingHttpPool(None, timeout_seconds=5)
        echoed: list[str] = []
        try:
            pool.session().get(f"{self.base_url}/set-cookie")

            def fetch_from_another_thread() -> None:
                value = pool.session().get(f"{self.base_url}/echo-cookie").json()["cookie"]
                echoed.append(value)

            thread = threading.Thread(target=fetch_from_another_thread)
            thread.start()
            thread.join(timeout=3)
            self.assertFalse(thread.is_alive())
            self.assertIn("server_cookie=kept", echoed[0])
        finally:
            pool.close()

    def test_stealth_channel_is_lazy_single_flight_and_requires_business_confirmation(
        self,
    ) -> None:
        class FakeRawResponse:
            status = 200
            body = b"<html><body>cleared</body></html>"
            url = "https://protected.example.test/content"
            headers = {"content-type": "text/html; charset=utf-8"}
            history: list[object] = []
            encoding = "utf-8"

        class FakeContext:
            def __init__(self) -> None:
                self.imported: list[dict[str, object]] = []

            def add_cookies(self, cookies: list[dict[str, object]]) -> None:
                self.imported.extend(cookies)

            def cookies(self) -> list[dict[str, object]]:
                return self.imported + [
                    {
                        "name": "clearance",
                        "value": "shared",
                        "domain": ".example.test",
                        "path": "/",
                        "secure": True,
                        "expires": time.time() + 60,
                    }
                ]

        class FakeStealthySession:
            instances: list["FakeStealthySession"] = []

            def __init__(self, **kwargs: object) -> None:
                self.kwargs = kwargs
                self.context = FakeContext()
                self.fetch_calls: list[tuple[str, dict[str, object]]] = []
                self.closed = False
                self.instances.append(self)

            def __enter__(self) -> "FakeStealthySession":
                return self

            def __exit__(self, *_args: object) -> None:
                self.closed = True

            def fetch(self, url: str, **kwargs: object) -> FakeRawResponse:
                self.fetch_calls.append((url, kwargs))
                return FakeRawResponse()

        state = {
            "cookies": [
                {
                    "name": "session",
                    "value": "existing",
                    "domain": ".example.test",
                    "path": "/",
                    "secure": True,
                    "expires": time.time() + 60,
                }
            ]
        }
        with patch("threadsnap.scrapling_transport.StealthySession", FakeStealthySession):
            pool = ScraplingHttpPool(None, timeout_seconds=5)
            pool.close()
            self.assertEqual([], FakeStealthySession.instances)

            budget = BrowserResourceBudget(maximum=1)
            pool = ScraplingHttpPool(
                state,
                timeout_seconds=5,
                scope=ExecutionScopeKey(platform="fixture"),
                browser_budget=budget,
            )
            try:
                first = pool.recover_protected(
                    "https://protected.example.test/content",
                    observed_generation=0,
                    solve_cloudflare=True,
                )
                self.assertTrue(first.attempted)
                self.assertTrue(first.should_retry_http)
                self.assertEqual(0, pool.verified_recovery_generation)
                # 第二个并发请求仍携带旧代次，只复用首个浏览器结果。
                second = pool.recover_protected(
                    "https://protected.example.test/content",
                    observed_generation=0,
                    solve_cloudflare=True,
                )
                self.assertTrue(second.reused)
                self.assertEqual(first.generation, second.generation)
                pool.confirm_protected_recovery(second.generation)
                self.assertEqual(1, pool.verified_recovery_generation)
                instance = FakeStealthySession.instances[0]
                self.assertEqual(1, len(instance.fetch_calls))
                self.assertTrue(instance.closed)
                self.assertTrue(instance.kwargs["block_webrtc"])
                self.assertTrue(instance.kwargs["hide_canvas"])
                self.assertEqual(1, instance.kwargs["max_pages"])
                self.assertTrue(instance.fetch_calls[0][1]["solve_cloudflare"])
                self.assertEqual(0, instance.fetch_calls[0][1]["wait"])
                self.assertEqual(
                    "shared",
                    pool.cookies.for_url("https://protected.example.test/next")["clearance"],
                )
                stats = pool.stats_snapshot()
                self.assertEqual(
                    (1, 1, 1),
                    (
                        stats.browser_attempts,
                        stats.browser_reuses,
                        stats.confirmed_recoveries,
                    ),
                )
                self.assertEqual(
                    (0, 1, 1),
                    (
                        budget.snapshot().active,
                        budget.snapshot().peak,
                        budget.snapshot().acquisitions,
                    ),
                )
            finally:
                pool.close()
            self.assertTrue(FakeStealthySession.instances[0].closed)

    def test_global_browser_budget_serializes_scopes_without_sharing_cookies(self) -> None:
        class FakeRawResponse:
            status = 200
            body = b"ok"
            url = "https://fixture.example.test/"
            headers = {"content-type": "text/html; charset=utf-8"}
            history: list[object] = []
            encoding = "utf-8"

        class FakeContext:
            def __init__(self) -> None:
                self.imported: list[dict[str, object]] = []

            def add_cookies(self, cookies: list[dict[str, object]]) -> None:
                self.imported.extend(cookies)

            def cookies(self) -> list[dict[str, object]]:
                return self.imported

        class BlockingStealthySession:
            lock = threading.Lock()
            active = 0
            peak = 0
            instances: list["BlockingStealthySession"] = []

            def __init__(self, **_kwargs: object) -> None:
                self.context = FakeContext()
                self.instances.append(self)

            def __enter__(self) -> "BlockingStealthySession":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def fetch(self, _url: str, **_kwargs: object) -> FakeRawResponse:
                with self.lock:
                    type(self).active += 1
                    type(self).peak = max(type(self).peak, type(self).active)
                time.sleep(0.05)
                with self.lock:
                    type(self).active -= 1
                return FakeRawResponse()

        def state(value: str) -> dict[str, object]:
            return {
                "cookies": [
                    {
                        "name": "identity",
                        "value": value,
                        "domain": ".example.test",
                        "path": "/",
                        "secure": True,
                        "expires": time.time() + 60,
                    }
                ]
            }

        budget = BrowserResourceBudget(maximum=1)
        pools = [
            ScraplingHttpPool(
                state(value),
                timeout_seconds=5,
                scope=ExecutionScopeKey(platform=platform),
                browser_budget=budget,
            )
            for platform, value in (("alpha", "A"), ("beta", "B"))
        ]
        with patch("threadsnap.scrapling_transport.StealthySession", BlockingStealthySession):
            threads = [
                threading.Thread(
                    target=pool.recover_protected,
                    args=("https://fixture.example.test/",),
                    kwargs={"observed_generation": 0},
                )
                for pool in pools
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=2)
                self.assertFalse(thread.is_alive())

        try:
            self.assertEqual(1, BlockingStealthySession.peak)
            self.assertEqual(
                (0, 1, 2),
                (
                    budget.snapshot().active,
                    budget.snapshot().peak,
                    budget.snapshot().acquisitions,
                ),
            )
            imported_values = [
                {str(cookie["value"]) for cookie in instance.context.imported}
                for instance in BlockingStealthySession.instances
            ]
            self.assertCountEqual(imported_values, [{"A"}, {"B"}])
            self.assertEqual("alpha", pools[0].stats_snapshot().scope)
            self.assertEqual("beta", pools[1].stats_snapshot().scope)
        finally:
            for pool in pools:
                pool.close()

    def test_cookie_scope_filters_path_protocol_and_expiry(self) -> None:
        store = BrowserCookieStore(
            {
                "cookies": [
                    {
                        "name": "valid",
                        "value": "yes",
                        "domain": ".example.test",
                        "path": "/private",
                        "secure": True,
                        "expires": time.time() + 60,
                    },
                    {
                        "name": "expired",
                        "value": "no",
                        "domain": ".example.test",
                        "path": "/",
                        "secure": False,
                        "expires": time.time() - 1,
                    },
                ]
            }
        )
        self.assertEqual(store.for_url("https://sub.example.test/private/page"), {"valid": "yes"})
        self.assertEqual(store.for_url("http://sub.example.test/private/page"), {})
        self.assertEqual(store.for_url("https://other.test/private/page"), {})

    def test_more_specific_cookie_scope_wins_for_same_name(self) -> None:
        store = BrowserCookieStore()
        store.set("scope", "root", domain=".example.test", path="/")
        store.set("scope", "private", domain="sub.example.test", path="/private")
        self.assertEqual(
            store.for_url("https://sub.example.test/private/page"), {"scope": "private"}
        )

    def test_fetcher_session_does_not_add_hidden_retries(self) -> None:
        before = _Handler.request_counts.get("/error", 0)
        pool = ScraplingHttpPool(None, timeout_seconds=5)
        try:
            response = pool.session().get(f"{self.base_url}/error")
            self.assertEqual(response.status_code, 503)
        finally:
            pool.close()
        self.assertEqual(_Handler.request_counts.get("/error", 0) - before, 1)

    def test_all_formal_http_adapters_use_scrapling_pool(self) -> None:
        adapters = [
            DongchediCollector(None),
            AutohomeCollector(None),
            YicheCollector(None),
            DongchediReputationAdapter(None),
        ]
        try:
            self.assertTrue(
                all(isinstance(adapter.http, ScraplingHttpPool) for adapter in adapters)
            )
            self.assertEqual(
                ["dongchedi", "autohome", "yiche", "dongchedi-reputation"],
                [adapter.http.scope.platform for adapter in adapters],
            )
        finally:
            for adapter in adapters:
                adapter.close()

    def test_caller_scope_binds_to_platform_without_exposing_owner_in_stats(self) -> None:
        caller_scope = ExecutionScopeKey(owner="fixture-customer", credential="profile-7")
        collector = AutohomeCollector(None, execution_scope=caller_scope)
        try:
            self.assertEqual("autohome", collector.http.scope.platform)
            self.assertEqual("fixture-customer", collector.http.scope.owner)
            self.assertEqual("profile-7", collector.http.scope.credential)
            self.assertEqual("autohome", collector.http.stats_snapshot().scope)
        finally:
            collector.close()

        with self.assertRaises(ValueError):
            AutohomeCollector(
                None,
                execution_scope=ExecutionScopeKey(platform="yiche"),
            )

    def test_formal_transport_suppresses_full_request_url_info_logs(self) -> None:
        self.assertGreaterEqual(logging.getLogger("scrapling").getEffectiveLevel(), logging.WARNING)

    def test_pool_closes_every_thread_session_and_rejects_reuse(self) -> None:
        pool = ScraplingHttpPool(None, timeout_seconds=5)
        sessions = []

        def create_session() -> None:
            sessions.append(pool.session())

        threads = [threading.Thread(target=create_session) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=3)
        pool.close()

        self.assertEqual(len(sessions), 2)
        self.assertTrue(all(session._closed for session in sessions))
        with self.assertRaises(RuntimeError):
            pool.session()

    def test_current_thread_transport_rotation_preserves_shared_cookies(self) -> None:
        """轮换只替换当前线程连接，服务端新Cookie继续由共享存储注入。"""

        pool = ScraplingHttpPool(None, timeout_seconds=5)
        try:
            previous = pool.session()
            previous.get(f"{self.base_url}/set-cookie")

            replacement = pool.rotate_current_thread_session()
            echoed = replacement.get(f"{self.base_url}/echo-cookie").json()["cookie"]
            snapshot = pool.stats_snapshot()

            self.assertIsNot(previous, replacement)
            self.assertTrue(previous._closed)
            self.assertIn("server_cookie=kept", echoed)
            self.assertEqual((2, 1), (snapshot.http_requests, snapshot.http_rotations))
        finally:
            pool.close()


if __name__ == "__main__":
    unittest.main()
