#!/usr/bin/env bash
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  echo "ERROR: run as root: sudo bash deploy/install-system-deps.sh" >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PACKAGE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if ! command -v dnf >/dev/null 2>&1; then
  echo "ERROR: this package currently records CentOS Stream 10/dnf prerequisites; install equivalent packages for the actual distribution first" >&2
  exit 3
fi

if [[ ! -d "$PACKAGE_ROOT/rpms/repodata" ]]; then
  echo "ERROR: offline RPM repository metadata is missing: $PACKAGE_ROOT/rpms/repodata" >&2
  exit 3
fi
if [[ ! -s "$PACKAGE_ROOT/SYSTEM-PACKAGES.txt" ]]; then
  echo "ERROR: offline system package list is missing: $PACKAGE_ROOT/SYSTEM-PACKAGES.txt" >&2
  exit 3
fi

shopt -s nullglob
rpms=("$PACKAGE_ROOT"/rpms/*.rpm)
if ((${#rpms[@]} == 0)); then
  echo "ERROR: offline RPM directory is missing or empty: $PACKAGE_ROOT/rpms" >&2
  echo "Build the final package on a matching Linux host with deploy/assemble-offline-package.sh." >&2
  exit 3
fi

mapfile -t packages < <(grep -Ev '^[[:space:]]*(#|$)' "$PACKAGE_ROOT/SYSTEM-PACKAGES.txt")
if ((${#packages[@]} == 0)); then
  echo "ERROR: offline system package list has no package names" >&2
  exit 3
fi

# 将包目录作为本地仓库，只请求顶层运行组件。DNF 会复用目标机已安装的兼容
# 版本，并仅从包内仓库补齐缺失依赖，避免把全部递归 RPM 强制升级到制包日版本。
dnf --disablerepo='*' \
  --repofrompath="threadsnap-offline,file://$PACKAGE_ROOT/rpms" \
  --setopt=threadsnap-offline.gpgcheck=0 \
  --nogpgcheck \
  install -y "${packages[@]}"

python3 - <<'PY'
import sys
if sys.version_info < (3, 11):
    raise SystemExit(f"ERROR: Python 3.11+ required, found {sys.version.split()[0]}")
print(f"python={sys.version.split()[0]}")
PY

for command_name in nginx weston curl tar sha256sum systemctl; do
  command -v "$command_name" >/dev/null || {
    echo "ERROR: required command missing after install: $command_name" >&2
    exit 4
  }
done

echo "system dependencies ready"
