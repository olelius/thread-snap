"""Linux 离线部署封装的静态契约测试。"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy" / "linux"


class LinuxDeploymentPackageTests(unittest.TestCase):
    """防止正式部署包退回联网安装或暴露内部接口。"""

    def read(self, relative: str) -> str:
        return (ROOT / relative).read_text(encoding="utf-8-sig")

    def test_required_deployment_files_exist(self) -> None:
        required = [
            "deploy/linux/inspect-host.sh",
            "deploy/linux/assemble-offline-package.sh",
            "deploy/linux/install-system-deps.sh",
            "deploy/linux/install.sh",
            "deploy/linux/verify.sh",
            "deploy/linux/backup.sh",
            "deploy/linux/restore-backup.sh",
            "deploy/linux/rollback-release.sh",
            "deploy/linux/nginx/threadsnap.conf",
            "deploy/linux/nginx/nginx.conf",
            "deploy/linux/systemd/threadsnap.service",
            "deploy/linux/systemd/threadsnap-wayland.service",
            "deploy/linux/systemd/threadsnap-nginx.service",
            "deploy/linux/templates/threadsnap.env.example",
            "scripts/build-linux-deployment-package.ps1",
        ]
        self.assertEqual([], [path for path in required if not (ROOT / path).is_file()])

    def test_target_install_is_fully_offline(self) -> None:
        install = self.read("deploy/linux/install.sh")
        system_deps = self.read("deploy/linux/install-system-deps.sh")
        self.assertIn("--no-index", install)
        self.assertIn('"$PACKAGE_ROOT/wheelhouse"', install)
        self.assertIn('"$PACKAGE_ROOT/browsers/."', install)
        self.assertIn("package-local Chromium executable is missing", install)
        self.assertNotIn('patchright" install chromium', install)
        self.assertNotRegex(install, r"https?://")
        self.assertIn("--disablerepo='*'", system_deps)
        self.assertIn("--repofrompath=", system_deps)
        self.assertIn('"${packages[@]}"', system_deps)
        self.assertNotIn('install -y "${rpms[@]}"', system_deps)
        self.assertNotRegex(system_deps, r"https?://")
        self.assertIn('"${ID:-}" == "centos"', install)
        self.assertIn('"$(uname -m)" == "x86_64"', install)

    def test_linux_assembler_collects_all_dependency_classes(self) -> None:
        assembler = self.read("deploy/linux/assemble-offline-package.sh")
        self.assertIn("pip download --only-binary=:all:", assembler)
        self.assertIn('patchright" install --no-shell chromium', assembler)
        self.assertIn("dnf install -y epel-release", assembler)
        self.assertIn("crb enable", assembler)
        self.assertIn("weston", assembler)
        self.assertNotIn("xorg-x11-server-Xvfb", assembler)
        self.assertIn("dnf download --resolve --alldeps", assembler)
        self.assertIn('createrepo_c "$STAGE/rpms"', assembler)
        self.assertIn('"$STAGE/SYSTEM-PACKAGES.txt"', assembler)
        self.assertIn('tar -tzf "$ARCHIVE" > "$ARCHIVE_LIST"', assembler)
        self.assertNotIn('tar -tzf "$ARCHIVE" | grep -q', assembler)
        self.assertIn('dependency_mode="fully-offline"', assembler)
        self.assertIn('package_role="offline-deployment"', assembler)
        self.assertIn("installable=True", assembler)
        self.assertIn("final offline assembly requires a clean", assembler)

    def test_installer_keeps_app_version_separate_from_os_release(self) -> None:
        install = self.read("deploy/linux/install.sh")
        self.assertIn('APP_VERSION="${manifest_values[0]}"', install)
        self.assertIn('RELEASE_ID="${APP_VERSION}-${SOURCE_COMMIT:0:12}"', install)
        self.assertNotIn('RELEASE_ID="${VERSION}-${SOURCE_COMMIT:0:12}"', install)
        self.assertIn('"$STAGING_DIR/venv/bin/python"', install)
        self.assertIn("sed 's/\\r$//'", install)

    def test_nginx_preserves_boundaries_and_streaming(self) -> None:
        nginx = self.read("deploy/linux/nginx/threadsnap.conf")
        internal = nginx.index("location ^~ /internal/v1")
        public_api = nginx.index("location ^~ /api/v1/")
        self.assertLess(internal, public_api)
        self.assertIn("return 404", nginx[internal:public_api])
        self.assertIn("proxy_buffering off", nginx)
        self.assertIn("Sec-WebSocket-Protocol", nginx)
        self.assertIn("$http_sec_websocket_protocol", nginx)
        self.assertIn("try_files $uri $uri/ /index.html", nginx)

    def test_nginx_uses_dedicated_service_and_nonstandard_port_label(self) -> None:
        install = self.read("deploy/linux/install.sh")
        verify = self.read("deploy/linux/verify.sh")
        service = self.read("deploy/linux/systemd/threadsnap-nginx.service")
        self.assertIn("threadsnap-nginx.service", install)
        self.assertIn("threadsnap-nginx.service", verify)
        self.assertIn("/etc/threadsnap/nginx.conf", service)
        self.assertIn("semanage port -a -t http_port_t", install)
        self.assertIn("-t usr_t '/opt/threadsnap/releases(/.*)?'", install)
        self.assertIn(
            "-t httpd_sys_content_t '/opt/threadsnap/releases/[^/]+/frontend(/.*)?'", install
        )
        self.assertNotIn("systemctl enable --now nginx.service", install)

    def test_single_process_and_wayland_contract(self) -> None:
        service = self.read("deploy/linux/systemd/threadsnap.service")
        wayland = self.read("deploy/linux/systemd/threadsnap-wayland.service")
        self.assertIn("Requires=threadsnap-wayland.service", service)
        self.assertIn(
            "venv/bin/python -m threadsnap.cli serve --host 127.0.0.1 --port 8000", service
        )
        self.assertNotIn("--workers", service)
        self.assertIn("--backend=headless-backend.so", wayland)
        self.assertIn("--socket=wayland-99", wayland)
        self.assertIn("--width=1280 --height=800", wayland)
        self.assertIn("NoNewPrivileges=true", wayland)

    def test_browser_uses_wayland_when_socket_is_configured(self) -> None:
        runtime = self.read("src/threadsnap/browser_runtime.py")
        auth = self.read("src/threadsnap/auth.py")
        worker = self.read("src/threadsnap/worker.py")
        environment = self.read("deploy/linux/templates/threadsnap.env.example")
        self.assertIn('os.environ.get("WAYLAND_DISPLAY")', runtime)
        self.assertIn('"--ozone-platform=wayland"', runtime)
        self.assertIn("args=browser_launch_args()", auth)
        self.assertIn("args=browser_launch_args()", worker)
        self.assertIn("XDG_RUNTIME_DIR=/run/threadsnap-wayland", environment)
        self.assertIn("WAYLAND_DISPLAY=wayland-99", environment)

    def test_headed_browser_mode_is_consistent(self) -> None:
        for path in [
            ".env.example",
            "deploy/linux/templates/threadsnap.env.example",
        ]:
            value = self.read(path)
            self.assertIn("THREADSNAP_AUTH_BROWSER_HEADLESS=false", value)
            self.assertNotIn("THREADSNAP_AUTH_BROWSER_HEADLESS=true", value)

    def test_builder_manifest_is_not_installable(self) -> None:
        builder = self.read("scripts/build-linux-deployment-package.ps1")
        self.assertIn("package_role = 'offline-builder-input'", builder)
        self.assertIn("installable = $false", builder)
        self.assertIn("contains_credentials = $false", builder)
        self.assertIn("$frontendBuildRoot 'dist\\*'", builder)
        self.assertIn("pip wheel --no-deps", builder)
        self.assertIn("[Text.UTF8Encoding]::new($false)", builder)

    def test_collector_runtime_dependency_is_declared(self) -> None:
        pyproject = self.read("pyproject.toml")
        self.assertIn('"curl-cffi==0.16.0"', pyproject)
        self.assertIn('"playwright==1.61.0"', pyproject)
        self.assertIn('"scrapling[fetchers]==0.4.12"', pyproject)

    def test_templates_have_no_real_secret(self) -> None:
        template = self.read("deploy/linux/templates/threadsnap.env.example")
        match = re.search(r"^THREADSNAP_SESSION_FERNET_KEY=(.*)$", template, re.MULTILINE)
        self.assertIsNotNone(match)
        self.assertEqual("<FERNET_KEY>", match.group(1))
        self.assertNotIn("storage-state", template.lower())


if __name__ == "__main__":
    unittest.main()
