"""独立联通配置与汇总逻辑的合成测试。"""

from __future__ import annotations

import asyncio
import importlib.util
import io
import json
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


def load_candidate_a_module():
    """从固定候选源码加载可独立测试的导航辅助函数。"""

    path = SHARED.parent / "candidate-a" / "src" / "throughput.py"
    spec = importlib.util.spec_from_file_location("candidate_a_throughput_for_tests", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("候选 A 模块加载失败")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ConnectivityTests(unittest.TestCase):
    def test_linux_script_exports_shared_browser_path_before_candidate_a(self) -> None:
        script = (SHARED.parent / "linux" / "test-connectivity.sh").read_text(encoding="utf-8")
        export_position = script.index('export PLAYWRIGHT_BROWSERS_PATH="$ROOT/.runtime/browsers"')
        candidate_a_position = script.index("candidate_a_exit=127")
        self.assertLess(export_position, candidate_a_position)
        self.assertIn('timeout --signal=TERM --kill-after=15s 360s "$ROOT/.runtime/candidate-a/bin/python"', script)
        self.assertIn("timeout --signal=TERM --kill-after=15s 360s npm", script)

    def test_linux_script_replaces_started_runner_placeholder_after_failure(self) -> None:
        script = (SHARED.parent / "linux" / "test-connectivity.sh").read_text(encoding="utf-8")
        self.assertEqual(2, script.count('"status":"runner_failed_before_login_result"'))
        self.assertIn('grep -q \'"status":"runner_not_started"\'', script)

    def test_candidate_a_authenticated_navigation_uses_dom_ready_for_goto_and_stability(self) -> None:
        candidate_a = load_candidate_a_module()

        class FakePage:
            def __init__(self) -> None:
                self.goto_calls: list[dict[str, object]] = []
                self.load_states: list[tuple[str, float | None]] = []

            async def goto(self, url: str, **kwargs: object) -> str:
                self.goto_calls.append({"url": url, **kwargs})
                return "response"

            async def wait_for_load_state(self, state: str = "load", timeout: float | None = None) -> None:
                self.load_states.append((state, timeout))

        async def exercise() -> FakePage:
            page = FakePage()
            await candidate_a.setup_dom_ready_navigation(page)
            await candidate_a.setup_dom_ready_navigation(page)
            await page.goto("https://TARGET/ugc/article/1234567890123456789", referer="https://TARGET/")
            await page.wait_for_load_state(state="load", timeout=1234)
            return page

        page = asyncio.run(exercise())
        self.assertEqual("domcontentloaded", page.goto_calls[0]["wait_until"])
        self.assertEqual([("domcontentloaded", 1234)], page.load_states)
        source = (SHARED.parent / "candidate-a" / "src" / "throughput.py").read_text(encoding="utf-8")
        verify_login = source[source.index("async def verify_login(") : source.index("async def main_async(")]
        self.assertIn("await setup_dom_ready_navigation(page)", verify_login)
        self.assertIn("page_setup=setup_dom_ready_navigation", source)

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
        self.assertIn("await setup_login_resource_routing(page)", verify_login)
        self.assertIn("await setup_dom_ready_navigation(page)", verify_login)
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
        self.assertEqual(2, script.count("--manual-captcha-cdp-port"))
        self.assertIn("127.0.0.1:$port", script)
        self.assertIn("chrome://inspect/#devices", script)
        self.assertNotIn("sms_code", (SHARED.parent / "linux" / "config.example.json").read_text(encoding="utf-8"))
        self.assertIn("poc/linux/bootstrap-sms-session.sh", packager)
        self.assertIn('($hashLines -join "`n") + "`n"', packager)
        self.assertNotIn("WriteAllLines((Join-Path $staging 'SHA256SUMS')", packager)

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
        for marker in ("navigation_target", "navigation_document", "navigation_event", "navigation_pending", "navigation_action"):
            self.assertIn(marker, candidate_a)
            self.assertIn(marker, bootstrap_b)
        self.assertIn("action=wait_until_domcontentloaded", candidate_a)
        self.assertIn("action=wait_until_domcontentloaded", bootstrap_b)
        self.assertNotIn("window.stop()", candidate_a)
        self.assertNotIn("window.stop()", bootstrap_b)
        for marker in ("sms_send_evidence", "network_events", "countdown_visible", "verification_visible", "warning_markers"):
            self.assertIn(marker, bootstrap_a)
            self.assertIn(marker, bootstrap_b)
        self.assertIn('await page.wait_for_timeout(5_000)', bootstrap_a)
        self.assertIn('await page.waitForTimeout(5_000)', bootstrap_b)

    def test_visual_verification_waits_for_manual_cdp_before_sms_code(self) -> None:
        candidate_a = (SHARED.parent / "candidate-a" / "src" / "throughput.py").read_text(encoding="utf-8")
        candidate_b = (SHARED.parent / "candidate-b" / "src" / "throughput.ts").read_text(encoding="utf-8")
        bootstrap_a = candidate_a[candidate_a.index("async def bootstrap_sms_session(") : candidate_a.index("async def main_async(")]
        bootstrap_b = candidate_b[candidate_b.index("async function bootstrapSmsSession(") : candidate_b.index("async function main()")]

        self.assertIn('"--remote-debugging-address=127.0.0.1"', candidate_a)
        self.assertIn("'--remote-debugging-address=127.0.0.1'", candidate_b)
        self.assertIn("wait_for_manual_visual_verification", bootstrap_a)
        self.assertIn("waitForManualVisualVerification", bootstrap_b)
        self.assertLess(
            bootstrap_a.index("wait_for_manual_visual_verification"),
            bootstrap_a.index('read_sms_code, "candidate-a"'),
        )
        self.assertLess(
            bootstrap_b.index("waitForManualVisualVerification"),
            bootstrap_b.index("readSmsCode('candidate-b')"),
        )
        for marker in (
            "visual_verification_required",
            "manual_verification_completed",
            "sms_send_confirmed",
        ):
            self.assertIn(marker, bootstrap_a)
            self.assertIn(marker, bootstrap_b)

    def test_sms_bootstrap_allows_captcha_images_without_changing_other_routes(self) -> None:
        candidate_a = (SHARED.parent / "candidate-a" / "src" / "throughput.py").read_text(encoding="utf-8")
        candidate_b = (SHARED.parent / "candidate-b" / "src" / "throughput.ts").read_text(encoding="utf-8")
        bootstrap_a = candidate_a[candidate_a.index("async def setup_sms_navigation_diagnostics(") : candidate_a.index("async def first_visible(")]
        bootstrap_b = candidate_b[candidate_b.index("async function bootstrapSmsSession(") : candidate_b.index("async function main()")]

        self.assertIn('SMS_LOGIN_BLOCKED_RESOURCE_TYPES = LOGIN_BLOCKED_RESOURCE_TYPES - {"image", "imageset"}', candidate_a)
        self.assertIn("setup_login_resource_routing(page, SMS_LOGIN_BLOCKED_RESOURCE_TYPES)", bootstrap_a)
        self.assertIn("if (['media', 'font'].includes(kind)) await route.abort();", bootstrap_b)
        self.assertNotIn("if (['image', 'media', 'font'].includes(kind))", bootstrap_b)
        self.assertIn('"font", "image", "media"', candidate_a)
        self.assertIn("['image', 'media', 'font', 'stylesheet']", candidate_b)

    def test_prepare_uses_only_three_low_concurrency_samples(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.json"
            input_path = root / "connectivity-urls.txt"
            output = root / "runtime" / "config.json"
            state_by_candidate = {
                "candidate-a": {"cookies": [{"name": "fixture-a", "value": "session-a"}], "origins": []},
                "candidate-b": {"cookies": [{"name": "fixture-b", "value": "session-b"}], "origins": []},
            }
            for candidate, state in state_by_candidate.items():
                profile = root / "profiles" / candidate
                profile.mkdir(parents=True)
                (profile / "storage-state.json").write_text(json.dumps(state), encoding="utf-8")
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
                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    self.assertEqual(0, prepare_connectivity_config.main())
            prepared = json.loads(output.read_text(encoding="utf-8"))
            preparation = json.loads(stdout.getvalue())
            self.assertEqual(3, prepared["expected_count"])
            self.assertEqual(300, prepared["window_seconds"])
            self.assertTrue(prepared["capture_login_diagnostic"])
            self.assertEqual(1, prepared["candidate_a"]["concurrency"])
            self.assertEqual(1, prepared["candidate_b"]["concurrency"])
            self.assertEqual({"candidate-a": True, "candidate-b": True}, preparation["session_state_copied"])
            for config_key, candidate in (("candidate_a", "candidate-a"), ("candidate_b", "candidate-b")):
                connectivity_profile = root / "profiles" / f"connectivity-{candidate}"
                self.assertEqual(connectivity_profile.resolve(), Path(prepared[config_key]["profile_dir"]))
                copied = json.loads((connectivity_profile / "storage-state.json").read_text(encoding="utf-8"))
                self.assertEqual(state_by_candidate[candidate], copied)
            self.assertNotIn("session-a", stdout.getvalue())
            self.assertNotIn("session-b", stdout.getvalue())

    def test_prepare_removes_stale_connectivity_state_when_source_state_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "config.json"
            input_path = root / "connectivity-urls.txt"
            output = root / "runtime" / "config.json"
            stale_profile = root / "profiles" / "connectivity-candidate-a"
            stale_profile.mkdir(parents=True)
            (stale_profile / "storage-state.json").write_text('{"cookies":[{"value":"stale"}]}', encoding="utf-8")
            source.write_text(
                json.dumps(
                    {
                        "account": "fixture-account",
                        "password": "fixture-password",
                        "candidate_a": {"profile_dir": "profiles/candidate-a"},
                        "candidate_b": {"profile_dir": "profiles/candidate-b"},
                    }
                ),
                encoding="utf-8",
            )
            input_path.write_text("https://TARGET/ugc/article/1234567890123456789\n", encoding="utf-8")
            argv = [
                "prepare_connectivity_config.py",
                "--config", str(source),
                "--input", str(input_path),
                "--output", str(output),
                "--root", str(root),
            ]
            with patch.object(sys, "argv", argv):
                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    self.assertEqual(0, prepare_connectivity_config.main())
            preparation = json.loads(stdout.getvalue())
            self.assertEqual({"candidate-a": False, "candidate-b": False}, preparation["session_state_copied"])
            self.assertFalse((stale_profile / "storage-state.json").exists())

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

    def test_finalize_prioritizes_candidate_runtime_failure_over_login_guess(self) -> None:
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
                    json.dumps({"logged_in": candidate == "candidate-b"}),
                    encoding="utf-8",
                )
                (base / "summary.json").write_text(
                    json.dumps(
                        {
                            "result_count": 3 if candidate == "candidate-b" else 0,
                            "success_count": 3 if candidate == "candidate-b" else 0,
                            "contract_error_count": 0 if candidate == "candidate-b" else 1,
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
                "--candidate-a-exit", "1",
                "--candidate-b-exit", "0",
            ]
            with patch.object(sys, "argv", argv):
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(3, finalize_connectivity.main())
            summary = json.loads((result_dir / "connectivity-summary.json").read_text(encoding="utf-8"))
            self.assertFalse(summary["ready_for_2000"])
            self.assertEqual("inspect_candidate_runtime_or_contract_error", summary["next_action"])


if __name__ == "__main__":
    unittest.main()
