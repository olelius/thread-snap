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

shopt -s nullglob
rpms=("$PACKAGE_ROOT"/rpms/*.rpm)
if ((${#rpms[@]} == 0)); then
  echo "ERROR: offline RPM directory is missing or empty: $PACKAGE_ROOT/rpms" >&2
  echo "Build the final package on a matching Linux host with deploy/assemble-offline-package.sh." >&2
  exit 3
fi

dnf --disablerepo='*' install -y "${rpms[@]}"

python3 - <<'PY'
import sys
if sys.version_info < (3, 11):
    raise SystemExit(f"ERROR: Python 3.11+ required, found {sys.version.split()[0]}")
print(f"python={sys.version.split()[0]}")
PY

for command_name in nginx Xvfb curl tar sha256sum systemctl; do
  command -v "$command_name" >/dev/null || {
    echo "ERROR: required command missing after install: $command_name" >&2
    exit 4
  }
done

echo "system dependencies ready"
