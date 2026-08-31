"""Scrapling 统一传输层的本地、确定性合同测试。"""

from __future__ import annotations

import json
import logging
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from threadsnap.collectors.autohome import AutohomeCollector
from threadsnap.collectors.dongchedi import DongchediCollector
from threadsnap.collectors.yiche import YicheCollector
from threadsnap.reputation_dongchedi import DongchediReputationAdapter
from threadsnap.scrapling_transport import BrowserCookieStore, ScraplingHttpPool


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
        self.assertEqual(
            store.for_url("https://sub.example.test/private/page"), {"valid": "yes"}
        )
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
        finally:
            for adapter in adapters:
                adapter.close()

    def test_formal_transport_suppresses_full_request_url_info_logs(self) -> None:
        self.assertGreaterEqual(
            logging.getLogger("scrapling").getEffectiveLevel(), logging.WARNING
        )

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


if __name__ == "__main__":
    unittest.main()
