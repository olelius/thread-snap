#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
[[ -f .runtime/installed ]] || { echo "ERROR: 请先运行 ./poc/linux/install.sh" >&2; exit 2; }
touch .runtime/ready
echo "runner ready"
