#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
./poc/linux/preflight.sh

if command -v dnf >/dev/null; then
  if [[ "$(id -u)" == 0 ]]; then privilege=(); else privilege=(sudo); fi
  "${privilege[@]}" dnf install -y \
    alsa-lib atk at-spi2-atk cups-libs libdrm libXcomposite libXdamage libXfixes \
    libXrandr mesa-libgbm pango nss libxcb libxkbcommon gtk3
fi

mkdir -p .runtime
python3 -m venv .runtime/candidate-a
.runtime/candidate-a/bin/python -m pip install -r poc/candidate-a/requirements.lock

NODE_VERSION="22.17.0"
NODE_ARCHIVE_SHA256="325c0f1261e0c61bcae369a1274028e9cfb7ab7949c05512c5b1e630f7e80e12"
NODE_HOME="$ROOT/.runtime/node-v$NODE_VERSION-linux-x64"
if [[ ! -x "$NODE_HOME/bin/node" ]]; then
  archive="$ROOT/.runtime/node-v$NODE_VERSION-linux-x64.tar.xz"
  curl --fail --location --retry 3 \
    "https://nodejs.org/dist/v$NODE_VERSION/node-v$NODE_VERSION-linux-x64.tar.xz" \
    --output "$archive"
  echo "$NODE_ARCHIVE_SHA256  $archive" | sha256sum --check --status || {
    echo "ERROR: Node.js archive checksum mismatch" >&2
    exit 2
  }
  tar -xJf "$archive" -C "$ROOT/.runtime"
fi
export PATH="$NODE_HOME/bin:$PATH"
export PLAYWRIGHT_BROWSERS_PATH="$ROOT/.runtime/browsers"
npm --prefix poc/candidate-b ci
.runtime/candidate-a/bin/python -m patchright install chromium
npx --prefix poc/candidate-b playwright install chromium

touch .runtime/installed
echo "install ok"
