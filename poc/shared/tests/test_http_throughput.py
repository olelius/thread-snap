"""纯 HTTP 批量入口摘要与隔离契约测试。"""

from __future__ import annotations

import importlib.util
import sys
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "poc" / "candidate-a" / "src" / "http_throughput.py"
SPEC = importlib.util.spec_from_file_location("candidate_a_http_throughput", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def result(url: str, status: str, response_class: str, duration_ms: int) -> dict:
    """构造摘要测试所需的最小结果。"""

    now = datetime.now(timezone.utc).isoformat()
    post_id = url.rsplit("/", 1)[-1]
    success = status == "success"
    return {
        "schema_version": "1.0",
        "candidate": "candidate-a",
        "url": url,
        "url_sha256": MODULE.url_sha256(url),
        "input_post_id": post_id,
        "observed_post_id": post_id if success else None,
        "post_id_matches": success,
        "title_present": success,
        "body_present": success,
        "response_class": response_class,
        "control_hit": response_class in MODULE.CONTROL_CLASSES,
        "channel": "http",
        "status": status,
        "request_count": 1,
        "started_at": now,
        "ended_at": now,
        "duration_ms": duration_ms,
        "http_status": 200,
        "error_category": None if success else response_class,
    }


class HttpThroughputTests(unittest.TestCase):
    def test_summary_uses_valid_urls_and_marks_first_control(self) -> None:
        first = result("https://TARGET/ugc/article/1111111111111111111", "success", "post", 100)
        second = result("https://TARGET/ugc/article/2222222222222222222", "failed", "empty", 200)
        summary = MODULE.build_summary(
            results=[first, second],
            completion_offsets_ms={first["url"]: 100, second["url"]: 250},
            duration_ms=1000,
            concurrency=1,
        )
        self.assertEqual(1, summary["success_count"])
        self.assertEqual(1.0, summary["effective_urls_per_second"])
        self.assertEqual("empty", summary["first_control"]["response_class"])
        self.assertFalse(summary["meets_correctness_gate"])
        self.assertTrue(summary["direct_http_only"])

    def test_summary_rejects_non_http_channel_as_direct_only(self) -> None:
        item = result("https://TARGET/ugc/article/3333333333333333333", "success", "post", 100)
        item["channel"] = "browser-dom"
        summary = MODULE.build_summary(
            results=[item], completion_offsets_ms={item["url"]: 100}, duration_ms=1000, concurrency=1
        )
        self.assertFalse(summary["direct_http_only"])

    def test_partial_summary_uses_requested_count_as_valid_rate_denominator(self) -> None:
        item = result("https://TARGET/ugc/article/4444444444444444444", "success", "post", 100)
        summary = MODULE.build_summary(
            results=[item],
            completion_offsets_ms={item["url"]: 100},
            duration_ms=1000,
            concurrency=1,
            requested_count=500,
        )
        self.assertEqual(500, summary["input_count"])
        self.assertEqual(1, summary["result_count"])
        self.assertEqual(0.002, summary["final_valid_rate"])
        self.assertEqual(0.002, summary["result_coverage_rate"])
        self.assertFalse(summary["meets_correctness_gate"])


class HttpSpiderControlTests(unittest.IsolatedAsyncioTestCase):
    async def test_authenticated_bulk_pauses_after_first_content_control(self) -> None:
        url = "https://TARGET/ugc/article/5555555555555555555"
        spider = MODULE.DirectHttpSpider([url], concurrency=1, timeout_seconds=30, pause_on_control=True)
        pause_calls = 0

        def record_pause() -> None:
            nonlocal pause_calls
            pause_calls += 1

        spider.pause = record_pause
        request = MODULE.Request(
            url,
            sid="http",
            meta={"input_url": url, "started_at": MODULE.utc_now(), "started_perf": time.perf_counter()},
        )
        response = MODULE.Response(
            url=url,
            content="<html><body>请登录</body></html>",
            status=200,
            reason="OK",
            cookies={},
            headers={},
            request_headers={},
        )
        response.request = request
        items = [item async for item in spider.parse(response)]
        self.assertEqual(1, pause_calls)
        self.assertEqual("login", spider.pause_reason)
        self.assertEqual(1, len(items))
        self.assertEqual("login", items[0]["response_class"])


if __name__ == "__main__":
    unittest.main()
