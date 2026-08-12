"""认证 HTTP 有界 Session 恢复控制测试。"""

from __future__ import annotations

import importlib.util
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "poc" / "candidate-a" / "src"
SHARED = ROOT / "poc" / "shared"
sys.path[:0] = [str(SHARED), str(SOURCE)]

MODULE_PATH = SOURCE / "bounded_session_recovery.py"
SPEC = importlib.util.spec_from_file_location("candidate_a_bounded_session_recovery", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def record(url: str, response_class: str, session_ordinal: int, segment_kind: str) -> dict:
    """构造状态机测试所需的最小结果。"""

    success = response_class == "post"
    return {
        "url": url,
        "url_sha256": f"hash-{url[-1]}",
        "response_class": response_class,
        "status": "success" if success else "failed",
        "http_status": 200,
        "session_ordinal": session_ordinal,
        "segment_kind": segment_kind,
    }


class RecoveryControlTests(unittest.TestCase):
    def test_empty_refreshes_session_and_retries_trigger_url(self) -> None:
        urls = ["url-1", "url-2", "url-3"]
        gate_urls = ["gate-1", "gate-2", "gate-3"]
        bulk_calls: list[tuple[int, list[str]]] = []

        def obtain(ordinal: int, reason: str) -> dict:
            return {"success": True, "storage_state": Path(f"state-{ordinal}.json")}

        def execute(items: list[str], state: Path, ordinal: int, kind: str) -> dict:
            if kind == "gate":
                results = [record(url, "post", ordinal, kind) for url in items]
                return {"results": results, "events": list(results), "pause_reason": None}
            bulk_calls.append((ordinal, list(items)))
            if ordinal == 1:
                results = [record(items[0], "post", ordinal, kind), record(items[1], "empty", ordinal, kind)]
                return {"results": results, "events": list(results), "pause_reason": "empty"}
            results = [record(url, "post", ordinal, kind) for url in items]
            return {"results": results, "events": list(results), "pause_reason": None}

        outcome = MODULE.execute_recovery_control(
            urls=urls,
            gate_urls=gate_urls,
            max_recoveries=2,
            deadline=time.monotonic() + 60,
            initial_storage_state=Path("initial.json"),
            obtain_session=obtain,
            execute_segment=execute,
        )

        self.assertEqual([(1, urls), (2, ["url-2", "url-3"])], bulk_calls)
        self.assertEqual(urls, [item["url"] for item in outcome["final_results"]])
        self.assertEqual(0, outcome["remaining_count"])
        refresh = [event for event in outcome["recovery_events"] if event["event"] == "session_refresh"]
        self.assertEqual(1, len(refresh))
        self.assertEqual("bulk_control", refresh[0]["recovery_scope"])
        self.assertTrue(refresh[0]["trigger_recovered"])

    def test_stops_when_recovery_budget_is_exhausted(self) -> None:
        urls = ["url-1", "url-2"]
        gate_urls = ["gate-1", "gate-2", "gate-3"]

        def obtain(ordinal: int, reason: str) -> dict:
            return {"success": True, "storage_state": Path(f"state-{ordinal}.json")}

        def execute(items: list[str], state: Path, ordinal: int, kind: str) -> dict:
            if kind == "gate":
                results = [record(url, "post", ordinal, kind) for url in items]
                return {"results": results, "events": list(results), "pause_reason": None}
            result = record(items[0], "empty", ordinal, kind)
            return {"results": [result], "events": [result], "pause_reason": "empty"}

        outcome = MODULE.execute_recovery_control(
            urls=urls,
            gate_urls=gate_urls,
            max_recoveries=1,
            deadline=time.monotonic() + 60,
            initial_storage_state=Path("initial.json"),
            obtain_session=obtain,
            execute_segment=execute,
        )

        self.assertEqual("max_recoveries_exhausted", outcome["stop_reason"])
        self.assertEqual("url-1", outcome["final_results"][0]["url"])
        self.assertEqual(1, outcome["remaining_count"])

    def test_captcha_does_not_trigger_login_loop(self) -> None:
        urls = ["url-1"]
        gate_urls = ["gate-1", "gate-2", "gate-3"]
        refresh_calls = 0

        def obtain(ordinal: int, reason: str) -> dict:
            nonlocal refresh_calls
            refresh_calls += 1
            return {"success": True, "storage_state": Path(f"state-{ordinal}.json")}

        def execute(items: list[str], state: Path, ordinal: int, kind: str) -> dict:
            if kind == "gate":
                results = [record(url, "post", ordinal, kind) for url in items]
                return {"results": results, "events": list(results), "pause_reason": None}
            result = record(items[0], "captcha", ordinal, kind)
            return {"results": [result], "events": [result], "pause_reason": "captcha"}

        outcome = MODULE.execute_recovery_control(
            urls=urls,
            gate_urls=gate_urls,
            max_recoveries=2,
            deadline=time.monotonic() + 60,
            initial_storage_state=Path("initial.json"),
            obtain_session=obtain,
            execute_segment=execute,
        )

        self.assertEqual("captcha", outcome["stop_reason"])
        self.assertEqual(0, refresh_calls)

    def test_unusable_initial_state_refreshes_before_bulk(self) -> None:
        urls = ["url-1"]
        gate_urls = ["gate-1", "gate-2", "gate-3"]
        refreshed = False

        def obtain(ordinal: int, reason: str) -> dict:
            nonlocal refreshed
            refreshed = True
            self.assertEqual("session_state_unusable", reason)
            return {"success": True, "storage_state": Path(f"state-{ordinal}.json")}

        def execute(items: list[str], state: Path, ordinal: int, kind: str) -> dict:
            if kind == "gate" and ordinal == 1:
                raise ValueError("fixture state is invalid")
            results = [record(url, "post", ordinal, kind) for url in items]
            return {"results": results, "events": list(results), "pause_reason": None}

        outcome = MODULE.execute_recovery_control(
            urls=urls,
            gate_urls=gate_urls,
            max_recoveries=1,
            deadline=time.monotonic() + 60,
            initial_storage_state=Path("invalid.json"),
            obtain_session=obtain,
            execute_segment=execute,
        )

        self.assertTrue(refreshed)
        self.assertEqual(0, outcome["remaining_count"])
        self.assertEqual("post", outcome["final_results"][0]["response_class"])


if __name__ == "__main__":
    unittest.main()
