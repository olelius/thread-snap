"""访问失败脱敏诊断的结构与泄漏边界测试。"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

SHARED = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SHARED))

from access_diagnostic import build_access_diagnostic  # noqa: E402


class AccessDiagnosticTests(unittest.TestCase):
    def test_diagnostic_keeps_shape_without_raw_page_url_or_cookie(self) -> None:
        input_url = "https://TARGET/ugc/article/1234567890123456789?private=query"
        document = "<html><head><title>安全验证</title><script>byted_acrawler</script></head><body>滑动验证</body></html>"
        diagnostic = build_access_diagnostic(
            candidate="candidate-a",
            trigger="first_empty",
            sequence=1,
            attempt=2,
            input_url=input_url,
            final_url=input_url,
            http_status=200,
            response_class="empty",
            document=document,
            cookies=[{"name": "session_name", "value": "secret-cookie-value"}],
            cookie_shape_available=True,
            main_document_responses=[{"status": 200, "target": "post"}],
        )
        serialized = json.dumps(diagnostic, ensure_ascii=False)
        self.assertEqual("post", diagnostic["final_url_kind"])
        self.assertTrue(diagnostic["final_url_matches_input"])
        self.assertEqual(1, diagnostic["cookie_count"])
        self.assertTrue(diagnostic["cookie_shape_available"])
        self.assertIn("verification", diagnostic["marker_hits"])
        self.assertIn("slider", diagnostic["marker_hits"])
        self.assertIn("acrawler", diagnostic["marker_hits"])
        self.assertNotIn(input_url, serialized)
        self.assertNotIn(document, serialized)
        self.assertNotIn("session_name", serialized)
        self.assertNotIn("secret-cookie-value", serialized)


if __name__ == "__main__":
    unittest.main()
