"""统一契约和分类规则的合成测试。"""

from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

SHARED = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SHARED))

from contract import classify_document, extract_input_post_id, url_sha256, validate_result  # noqa: E402


class ContractTests(unittest.TestCase):
    def test_extracts_both_supported_article_routes(self) -> None:
        post_id = "1234567890123456789"
        self.assertEqual(post_id, extract_input_post_id(f"https://TARGET/article/{post_id}"))
        self.assertEqual(post_id, extract_input_post_id(f"https://TARGET/ugc/article/{post_id}"))

    def test_classification_cases(self) -> None:
        cases = json.loads((SHARED / "classification-cases.json").read_text(encoding="utf-8"))
        for case in cases:
            with self.subTest(case=case["name"]):
                actual = classify_document(
                    case["final_url"], case["http_status"], case["document"], case["input_post_id"]
                )
                self.assertEqual(case["expected_response_class"], actual["response_class"])
                self.assertEqual(case["expected_status"], actual["status"])
                if actual["response_class"] != "post":
                    self.assertFalse(actual["post_id_matches"])

    def test_success_requires_id_and_proof(self) -> None:
        url = "https://TARGET/ugc/article/1234567890123456789"
        now = datetime.now(timezone.utc).isoformat()
        record = {
            "schema_version": "1.0",
            "candidate": "candidate-a",
            "url": url,
            "url_sha256": url_sha256(url),
            "input_post_id": "1234567890123456789",
            "observed_post_id": None,
            "post_id_matches": False,
            "title_present": False,
            "body_present": False,
            "response_class": "post",
            "control_hit": False,
            "channel": "http",
            "status": "success",
            "request_count": 1,
            "started_at": now,
            "ended_at": now,
            "duration_ms": 0,
            "http_status": 200,
            "error_category": None,
        }
        errors = validate_result(record, "candidate-a")
        self.assertTrue(any("success" in error for error in errors))

    def test_deadline_not_started_allows_zero_request_count(self) -> None:
        url = "https://TARGET/ugc/article/1234567890123456789"
        now = datetime.now(timezone.utc).isoformat()
        record = {
            "schema_version": "1.0",
            "candidate": "candidate-a",
            "url": url,
            "url_sha256": url_sha256(url),
            "input_post_id": "1234567890123456789",
            "observed_post_id": None,
            "post_id_matches": False,
            "title_present": False,
            "body_present": False,
            "response_class": "error",
            "control_hit": False,
            "channel": "browser-dom",
            "status": "failed",
            "request_count": 0,
            "started_at": now,
            "ended_at": now,
            "duration_ms": 0,
            "http_status": None,
            "error_category": "deadline_not_started",
        }
        self.assertEqual([], validate_result(record, "candidate-a"))

    def test_login_initialization_failure_allows_zero_request_count(self) -> None:
        url = "https://TARGET/ugc/article/1234567890123456789"
        now = datetime.now(timezone.utc).isoformat()
        record = {
            "schema_version": "1.0",
            "candidate": "candidate-a",
            "url": url,
            "url_sha256": url_sha256(url),
            "input_post_id": "1234567890123456789",
            "observed_post_id": None,
            "post_id_matches": False,
            "title_present": False,
            "body_present": False,
            "response_class": "login",
            "control_hit": True,
            "channel": "browser-dom",
            "status": "blocked",
            "request_count": 0,
            "started_at": now,
            "ended_at": now,
            "duration_ms": 0,
            "http_status": None,
            "error_category": "login_initialization_failed",
        }
        self.assertEqual([], validate_result(record, "candidate-a"))


if __name__ == "__main__":
    unittest.main()
