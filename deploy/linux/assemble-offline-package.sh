#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PACKAGE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OUTPUT_DIR="${1:-$PWD/output}"

if [[ "$(uname -m)" != "x86_64" ]]; then
  echo "ERROR: current package target is x86_64, found $(uname -m)" >&2
  exit 2
fi
if ! command -v dnf >/dev/null 2>&1; then
  echo "ERROR: run this assembler on the target-compatible CentOS Stream 10 host" >&2
  exit 2
fi
if [[ "$(id -u)" -ne 0 ]]; then
  echo "ERROR: run with sudo/root so RPM dependencies can be resolved" >&2
  exit 2
fi

for required in PACKAGE-MANIFEST.json SHA256SUMS backend frontend deploy; do
  [[ -e "$PACKAGE_ROOT/$required" ]] || { echo "ERROR: missing builder input: $required" >&2; exit 3; }
done
(
  cd "$PACKAGE_ROOT"
  sha256sum -c SHA256SUMS
)

python3 - <<'PY'
import sys
if sys.version_info < (3, 11):
    raise SystemExit(f"ERROR: Python 3.11+ required, found {sys.version.split()[0]}")
PY

if ! dnf download --help >/dev/null 2>&1; then
  dnf install -y dnf-plugins-core
fi

# CentOS Stream 10 已移除 Xorg/Xvfb。Weston 位于 EPEL，部分依赖位于 CRB；
# 只在联网制包阶段启用这些仓库，最终目标机仍使用包内 RPM 纯离线安装。
if ! rpm -q epel-release >/dev/null 2>&1; then
  dnf install -y epel-release
fi
if ! dnf repolist --enabled | awk '{print $1}' | grep -qx crb; then
  crb enable
fi

readarray -t manifest_values < <(
  python3 - "$PACKAGE_ROOT/PACKAGE-MANIFEST.json" <<'PY'
import json, sys
manifest = json.load(open(sys.argv[1], encoding="utf-8-sig"))
print(manifest["package"])
print(manifest["version"])
print(manifest["source_commit"])
print(str(manifest.get("source_dirty", True)).lower())
print(str(manifest.get("installable", True)).lower())
PY
)
BASE_NAME="${manifest_values[0]}"
VERSION="${manifest_values[1]}"
SOURCE_COMMIT="${manifest_values[2]}"
[[ "${manifest_values[3]}" == "false" && "${manifest_values[4]}" == "false" ]] || {
  echo "ERROR: final offline assembly requires a clean, non-installable builder input" >&2
  exit 3
}
FINAL_NAME="${BASE_NAME%-linux-builder}-centos-stream-10-x86_64-offline"

mkdir -p "$OUTPUT_DIR"
WORK_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/threadsnap-offline.XXXXXX")"
cleanup() { rm -rf -- "$WORK_ROOT"; }
trap cleanup EXIT
STAGE="$WORK_ROOT/$FINAL_NAME"
cp -a "$PACKAGE_ROOT" "$STAGE"
rm -f "$STAGE/SHA256SUMS"
mkdir -p "$STAGE/wheelhouse" "$STAGE/browsers" "$STAGE/rpms"

APP_WHEEL="$(find "$STAGE/backend" -maxdepth 1 -type f -name 'threadsnap-*.whl' -print -quit)"
[[ -n "$APP_WHEEL" ]] || { echo "ERROR: ThreadSnap wheel missing" >&2; exit 4; }

python3 -m pip download --only-binary=:all: --dest "$STAGE/wheelhouse" "$APP_WHEEL"
python3 -m venv "$WORK_ROOT/verify-venv"
"$WORK_ROOT/verify-venv/bin/python" -m pip install \
  --no-index --find-links "$STAGE/wheelhouse" "$APP_WHEEL"
"$WORK_ROOT/verify-venv/bin/python" -m pip check

PLAYWRIGHT_BROWSERS_PATH="$STAGE/browsers" \
  "$WORK_ROOT/verify-venv/bin/patchright" install --no-shell chromium

rpm_packages=(
  python3 python3-pip nginx epel-release weston
  tar gzip curl ca-certificates shadow-utils findutils util-linux procps-ng iproute
  policycoreutils-python-utils
  alsa-lib atk at-spi2-atk cups-libs libdrm libXcomposite libXdamage libXfixes
  libXrandr mesa-libgbm pango nss libxcb libxkbcommon gtk3
)
dnf download --resolve --alldeps --destdir "$STAGE/rpms" "${rpm_packages[@]}"

python3 - "$STAGE/PACKAGE-MANIFEST.json" "$FINAL_NAME" <<'PY'
import json, os, platform, sys
from pathlib import Path

path = Path(sys.argv[1])
manifest = json.loads(path.read_text(encoding="utf-8-sig"))
manifest.update(
    package=sys.argv[2],
    package_role="offline-deployment",
    installable=True,
    dependency_mode="fully-offline",
    assembled_on={
        "platform": platform.platform(),
        "python": platform.python_version(),
        "machine": platform.machine(),
    },
)
path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY

find "$STAGE" -type f \
  ! -name SHA256SUMS \
  ! -path '*/__pycache__/*' \
  -print0 | sort -z | while IFS= read -r -d '' file; do
    relative="${file#"$STAGE/"}"
    printf '%s  %s\n' "$(sha256sum "$file" | awk '{print $1}')" "$relative"
  done > "$STAGE/SHA256SUMS"

ARCHIVE="$OUTPUT_DIR/$FINAL_NAME.tar.gz"
tar -czf "$ARCHIVE" -C "$WORK_ROOT" "$FINAL_NAME"
(
  cd "$OUTPUT_DIR"
  sha256sum "$(basename "$ARCHIVE")" > "$(basename "$ARCHIVE").sha256"
)

tar -tzf "$ARCHIVE" | grep -q "/wheelhouse/"
tar -tzf "$ARCHIVE" | grep -q "/browsers/"
tar -tzf "$ARCHIVE" | grep -q "/rpms/"

echo "offline_archive=$ARCHIVE"
echo "offline_sha256=$ARCHIVE.sha256"
echo "source_commit=$SOURCE_COMMIT"
echo "version=$VERSION"
