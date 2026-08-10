#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

[[ "$(uname -s)" == "Linux" ]] || { echo "ERROR: 仅支持 Linux" >&2; exit 2; }
[[ "$(uname -m)" == "x86_64" ]] || { echo "ERROR: 当前包只验证 x86_64" >&2; exit 2; }
for command in bash sha256sum tar ps awk sed grep curl timeout; do
  command -v "$command" >/dev/null || { echo "ERROR: 缺少命令 $command" >&2; exit 2; }
done

python_bin="$(command -v python3 || true)"
[[ -n "$python_bin" ]] || { echo "ERROR: 缺少 Python 3" >&2; exit 2; }
"$python_bin" - <<'PY'
import sys
if sys.version_info < (3, 11):
    raise SystemExit("ERROR: Python 必须 >= 3.11")
print("python", sys.version.split()[0])
PY

libc_version="$(ldd --version 2>&1 | head -n 1 || true)"
echo "kernel $(uname -r)"
echo "arch $(uname -m)"
echo "libc $libc_version"
echo "preflight ok"
