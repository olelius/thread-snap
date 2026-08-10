"""独立联通配置与汇总逻辑的合成测试。"""

from __future__ import annotations

import json
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

SHARED = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SHARED))

import finalize_connectivity  # noqa: E402
import prepare_connectivity_config  # noqa: E402


class ConnectivityTests(unittest.TestCase):
    def test_linux_script_exports_shared_browser_path_before_candidate_a(self) -> None:
        script = (SHARED.parent / "linux" / "test-connectivity.sh").read_text(encoding="utf-8")
        export_position = script.index('export PLAYWRIGHT_BROWSERS_PATH="$ROOT/.runtime/browsers"')
        candidate_a_position = script.index("candidate_a_exit=127")
        self.assertLess(export_position, candidate_a_position)
        self.assertIn('timeout --signal=TERM --kill-after=15s 360s "$ROOT/.runtime/candidate-a/bin/python"', script)
        self.assertIn("timeout --signal=TERM --kill-after=15s 360s npm", script)

    def test_both_candidates_select_password_login_before_filling_credentials(self) -> None:
        candidate_a = (SHARED.parent / "candidate-a" / "src" / "throughput.py").read_text(encoding="utf-8")
        candidate_b = (SHARED.parent / "candidate-b" / "src" / "throughput.ts").read_text(encoding="utf-8")
        self.assertLess(candidate_a.index('get_by_text("密码登录", exact=True)'), candidate_a.index("account_input.fill(account)"))
        self.assertLess(candidate_b.index("getByText('密码登录', { exact: true })"), candidate_b.index("accountInput.fill(config.account)"))
        self.assertNotIn('locator("button").last.click', candidate_a)
        self.assertNotIn("locator('button').last().click", candidate_b)

    def test_login_diagnostics_identify_forced_sms_and_candidate_a_drops_nonessential_resources(self) -> None:
        candidate_a = (SHARED.parent / "candidate-a" / "src" / "throughput.py").read_text(encoding="utf-8")
        candidate_b = (SHARED.parent / "candidate-b" / "src" / "throughput.ts").read_text(encoding="utf-8")
        marker = "为保证账号安全，请使用手机验证码登录"
        self.assertIn(marker, candidate_a)
        self.assertIn(marker, candidate_b)
        self.assertIn('"secondary_sms_required": SECONDARY_SMS_MARKER in body_text', candidate_a)
        self.assertIn('secondary_sms_required: bodyText.includes(SECONDARY_SMS_MARKER)', candidate_b)
        verify_login = candidate_a[candidate_a.index("async def verify_login(") : candidate_a.index("async def main_async(")]
        self.assertIn("page_setup=page_setup", verify_login)
        self.assertIn("route.request.resource_type in LOGIN_BLOCKED_RESOURCE_TYPES", verify_login)
        self.assertNotIn("disable_resources=True", verify_login)

    def test_manual_sms_bootstrap_keeps_candidates_isolated_and_interactive(self) -> None:
        candidate_a = (SHARED.parent / "candidate-a" / "src" / "throughput.py").read_text(encoding="utf-8")
        candidate_b = (SHARED.parent / "candidate-b" / "src" / "throughput.ts").read_text(encoding="utf-8")
        script = (SHARED.parent / "linux" / "bootstrap-sms-session.sh").read_text(encoding="utf-8")
        packager = (SHARED.parents[1] / "scripts" / "build-linux-poc-package.ps1").read_text(encoding="utf-8")
        self.assertIn('parser.add_argument("--bootstrap-sms", action="store_true")', candidate_a)
        self.assertIn("if (options.bootstrapSms)", candidate_b)
        self.assertIn("[[ ! -t 0 || ! -t 1 ]]", script)
        self.assertLess(script.index("run_candidate_a"), script.index("run_candidate_b"))
        self.assertEqual(2, script.count("--bootstrap-sms"))
        self.assertNotIn("sms_code", (SHARED.parent / "linux" / "config.example.json").read_text(encoding="utf-8"))
        self.assertIn("poc/linux/bootstrap-sms-session.sh", packager)

    def test_sms_bootstrap_enters_login_directly_and_reports_click_progress(self) -> None:
        candidate_a = (SHARED.parent / "candidate-a" / "src" / "throughput.py").read_text(encoding="utf-8")
        candidate_b = (SHARED.parent / "candidate-b" / "src" / "throughput.ts").read_text(encoding="utf-8")
        bootstrap_a = candidate_a[candidate_a.index("async def bootstrap_sms_session(") : candidate_a.index("async def main_async(")]
        bootstrap_b = candidate_b[candidate_b.index("async function bootstrapSmsSession(") : candidate_b.index("async function main()")]
        self.assertIn("build_sms_login_url(url)", bootstrap_a)
        self.assertIn("buildSmsLoginUrl(probeUrl)", bootstrap_b)
        self.assertNotIn("await session.fetch(\n            url,", bootstrap_a)
        self.assertNotIn("crawler.run([{ url: probeUrl", bootstrap_b)
        self.assertIn("sms_page_ready=candidate-a", bootstrap_a)
        self.assertIn("sms_request_clicked=candidate-a", bootstrap_a)
        self.assertIn("sms_page_ready=candidate-b", bootstrap_b)
        self.assertIn("sms_request_clicked=candidate-b", bootstrap_b)
        for marker in ("navigation_target", "navigation_document", "navigation_event"):
            self.assertIn(marker, candidate_a)
            self.assertIn(marker, bootstrap_b)

    def test_prepare_uses_only_three_low_concurrency_samples(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.json"
            input_path = root / "connectivity-urls.txt"
            output = root / "runtime" / "config.json"
            source.write_text(
                json.dumps(
                    {
                        "account": "fixture-account",
                        "password": "fixture-password",
                        "input_file": "input-urls.txt",
                        "expected_count": 2000,
                        "window_seconds": 3600,
                        "candidate_a": {"concurrency": 8},
                        "candidate_b": {"concurrency": 8},
                    }
                ),
                encoding="utf-8",
            )
            input_path.write_text(
                "\n".join(f"https://TARGET/ugc/article/123456789012345678{i}" for i in range(3)) + "\n",
                encoding="utf-8",
            )
            argv = [
                "prepare_connectivity_config.py",
                "--config", str(source),
                "--input", str(input_path),
                "--output", str(output),
                "--root", str(root),
            ]
            with patch.object(sys, "argv", argv):
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(0, prepare_connectivity_config.main())
            prepared = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(3, prepared["expected_count"])
            self.assertEqual(300, prepared["window_seconds"])
            self.assertTrue(prepared["capture_login_diagnostic"])
            self.assertEqual(1, prepared["candidate_a"]["concurrency"])
            self.assertEqual(1, prepared["candidate_b"]["concurrency"])

    def test_finalize_requires_network_and_both_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result_dir = Path(directory)
            (result_dir / "network.json").write_text(
                json.dumps(
                    {
                        "transport_ready": True,
                        "dns": {"ok": True},
                        "tcp": {"ok": True},
                        "tls": {"ok": True},
                        "http": {"ok": True, "status": 200},
                    }
                ),
                encoding="utf-8",
            )
            for candidate in ("candidate-a", "candidate-b"):
                base = result_dir / candidate
                base.mkdir()
                (base / "login-result.json").write_text(
                    json.dumps({"logged_in": True, "verification_required": False}), encoding="utf-8"
                )
                (base / "summary.json").write_text(
                    json.dumps(
                        {
                            "result_count": 3,
                            "success_count": 2,
                            "contract_error_count": 0,
                            "status_counts": {"success": 2, "failed": 1},
                            "response_class_counts": {"post": 2, "error": 1},
                        }
                    ),
                    encoding="utf-8",
                )
            argv = [
                "finalize_connectivity.py",
                "--result-dir", str(result_dir),
                "--preflight-exit", "0",
                "--healthcheck-exit", "0",
                "--network-exit", "0",
                "--candidate-a-exit", "0",
                "--candidate-b-exit", "0",
            ]
            with patch.object(sys, "argv", argv):
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(0, finalize_connectivity.main())
            summary = json.loads((result_dir / "connectivity-summary.json").read_text(encoding="utf-8"))
            self.assertTrue(summary["ready_for_2000"])
            self.assertEqual("run_2000_url_test", summary["next_action"])


if __name__ == "__main__":
    unittest.main()
