"""恢复与回退必须使用已安装Nginx端口，不允许误探默认80。"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAMES = ("rollback-release.sh", "restore-backup.sh")
SCRIPTS = {name: (ROOT / "deploy/linux" / name).read_text(encoding="utf-8") for name in NAMES}
CODE = {
    name: script.split("<<'PORT_PY'\n", 1)[1].split("\nPORT_PY\n", 1)[0]
    for name, script in SCRIPTS.items()
}


class MaintenanceListenPortTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.config = self.root / "nginx-site.conf"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def parse(self, config: str) -> subprocess.CompletedProcess:
        self.config.write_text(config, encoding="utf-8")
        return subprocess.run(
            [sys.executable, "-c", CODE[NAMES[0]], str(self.config)],
            capture_output=True, text=True, timeout=10,
        )

    def test_same_preflight_before_stop_and_explicit_verification_arguments(self) -> None:
        self.assertEqual(CODE[NAMES[0]], CODE[NAMES[1]])
        for name, script in SCRIPTS.items():
            with self.subTest(script=name):
                self.assertLess(script.index('LISTEN_PORT="$(python3'), script.index("systemctl stop "))
                calls = [line for line in script.splitlines() if "verify.sh" in line and line.startswith("if ! bash ")]
                self.assertEqual(1, len(calls))
                self.assertIn('--quick --listen-port "$LISTEN_PORT" --server-name _', calls[0])

    def test_integer_ipv4_ipv6_same_port_and_comments(self) -> None:
        cases = (
            ("server { listen 80; server_name _; }", "80"),
            ("server { listen 8088; server_name _; }", "8088"),
            ("server { listen 127.0.0.1:8088; }", "8088"),
            ("server { listen 0.0.0.0:8088; }", "8088"),
            ("server { listen [::]:8088 ipv6only=on; }", "8088"),
            ("server { listen 8088; listen [::]:8088; }", "8088"),
            ("# listen 80;\nserver { listen 8088; } # listen 9090;", "8088"),
        )
        for source, expected in cases:
            with self.subTest(source=source):
                result = self.parse(source)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual(expected, result.stdout.strip())

    def test_ambiguous_missing_implicit_and_invalid_ports_fail_closed(self) -> None:
        for source in (
            "server { listen 80; listen 8088; }", "server { server_name _; }",
            "server { listen 127.0.0.1; }", "server { listen [::]; }",
            "server { listen 0; }", "server { listen 65536; }",
            "server { listen 8088; listen 9090 }", "server { listen unix:/tmp/nginx.sock; }",
        ):
            with self.subTest(source=source):
                result = self.parse(source)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual("", result.stdout)

    def test_bash_fixture_passes_80_8088_and_refuses_ambiguity_before_stop_marker(self) -> None:
        """执行两脚本的原样端口段和verify调用；仅服务/验收脚本使用隔离标记替身。"""
        bash = shutil.which("bash")
        if not bash:
            git = shutil.which("git")
            candidate = Path(git).parent.parent / "bin/bash.exe" if git else None
            bash = str(candidate) if candidate and candidate.is_file() else None
        if not bash:
            self.skipTest("本机无Bash；Python解析门仍单独执行")
        verify = self.root / "verify.sh"
        capture = self.root / "verify-args.txt"
        stop_marker = self.root / "service-stopped.txt"
        verify.write_text(f'#!/usr/bin/env bash\nprintf "%s\\n" "$@" > "{capture.as_posix()}"\n', encoding="utf-8", newline="\n")
        for name, script in SCRIPTS.items():
            port_block = script.split('LISTEN_PORT="$(python3', 1)[1].split('\n)"', 1)[0]
            port_block = 'LISTEN_PORT="$(python3' + port_block + '\n)"\n'
            port_block = port_block.replace("/etc/threadsnap/nginx-site.conf", f'"{self.config.as_posix()}"')
            call = next(line for line in script.splitlines() if line.startswith("if ! bash ") and "verify.sh" in line)
            call = call.removeprefix("if ! ").removesuffix("; then")
            call = re.sub(r'bash .+?/verify\.sh"?', f'bash "{verify.as_posix()}"', call)
            harness = self.root / f"{name}.fixture.sh"
            harness.write_text(
                f'#!/usr/bin/env bash\nset -euo pipefail\npython3() {{ "{Path(sys.executable).as_posix()}" "$@"; }}\n'
                + port_block + f'printf stopped > "{stop_marker.as_posix()}"\n' + call + "\n",
                encoding="utf-8", newline="\n",
            )
            for source, expected in (("listen 80;", "80"), ("listen 8088;", "8088"), ("listen 80; listen 8088;", None)):
                with self.subTest(script=name, source=source):
                    capture.unlink(missing_ok=True)
                    stop_marker.unlink(missing_ok=True)
                    self.config.write_text(f"server {{ {source} server_name _; }}", encoding="utf-8")
                    result = subprocess.run([bash, str(harness)], capture_output=True, text=True, timeout=15)
                    if expected is None:
                        self.assertNotEqual(0, result.returncode)
                        self.assertFalse(stop_marker.exists())
                        self.assertFalse(capture.exists())
                    else:
                        self.assertEqual(0, result.returncode, result.stderr)
                        self.assertTrue(stop_marker.exists())
                        self.assertEqual(["--quick", "--listen-port", expected, "--server-name", "_"], capture.read_text().splitlines())


if __name__ == "__main__":
    unittest.main()
