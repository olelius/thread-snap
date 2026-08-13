"""Candidate A 内容 API Linux 包装与打包清单测试。"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


class LinuxContentPackageTests(unittest.TestCase):
    def test_package_contains_content_runner_and_all_local_python_dependencies(self) -> None:
        build = (ROOT / "scripts" / "build-linux-poc-package.ps1").read_text(encoding="utf-8")
        packaged = set(re.findall(r"'([^']+)'", build))
        required = {
            "poc/linux/run-content-api.sh",
            "poc/candidate-a/src/content_extraction.py",
            "poc/candidate-a/src/http_throughput.py",
            "poc/shared/contract.py",
            "poc/shared/session_handoff.py",
        }
        self.assertEqual(set(), required - packaged)

    def test_linux_runner_gates_before_bulk_and_reuses_scrapling_state(self) -> None:
        runner = (ROOT / "poc" / "linux" / "run-content-api.sh").read_text(encoding="utf-8")
        gate = runner.index("stage=content-api-gate")
        bulk = runner.index("stage=content-api-bulk")
        self.assertLess(gate, bulk)
        self.assertIn('profile_dir / "storage-state.json"', runner)
        self.assertIn("poc/candidate-a/src/content_extraction.py", runner)
        self.assertIn("bootstrap-sms-session.sh candidate-a", runner)
        self.assertIn("resource-metrics.csv", runner)
        self.assertIn("content-api-results", runner)
        self.assertNotIn("AsyncDynamicSession", runner)
        self.assertNotIn("DynamicSession", runner)

    def test_example_config_has_bounded_content_api_gate(self) -> None:
        config = json.loads((ROOT / "poc" / "linux" / "config.example.json").read_text(encoding="utf-8"))
        candidate = config["candidate_a"]
        self.assertEqual(3, candidate["content_api_gate_count"])
        self.assertEqual(8, candidate["content_api_concurrency"])


if __name__ == "__main__":
    unittest.main()
