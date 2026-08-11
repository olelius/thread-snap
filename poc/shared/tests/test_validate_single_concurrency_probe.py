import json
import sys
import tempfile
import unittest
from pathlib import Path

SHARED = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SHARED))

from validate_single_concurrency_probe import validate_probe  # noqa: E402


class ValidateSingleConcurrencyProbeTests(unittest.TestCase):
    def make_result(
        self,
        root: Path,
        *,
        logged_in: bool,
        response_class: str,
        success_count: int,
    ) -> Path:
        result = root / "result"
        result.mkdir()
        (result / "login-result.json").write_text(
            json.dumps({"logged_in": logged_in, "response_class": response_class}),
            encoding="utf-8",
        )
        (result / "summary.json").write_text(
            json.dumps(
                {
                    "input_count": 1,
                    "success_count": success_count,
                    "response_class_counts": {response_class: 1},
                }
            ),
            encoding="utf-8",
        )
        return result

    def test_accepts_authenticated_post_probe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = self.make_result(
                Path(directory), logged_in=True, response_class="post", success_count=1
            )
            evidence = validate_probe(result, 0)
            self.assertTrue(evidence["ready"])

    def test_rejects_login_probe_even_with_old_state_file_available(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = self.make_result(
                Path(directory), logged_in=False, response_class="login", success_count=0
            )
            evidence = validate_probe(result, 3)
            self.assertFalse(evidence["ready"])
            self.assertEqual(evidence["login_response_class"], "login")

    def test_rejects_empty_post_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = self.make_result(
                Path(directory), logged_in=True, response_class="empty", success_count=0
            )
            evidence = validate_probe(result, 0)
            self.assertFalse(evidence["ready"])
