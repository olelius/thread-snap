#!/usr/bin/env bash
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
status=0
./poc/linux/run-poc.sh candidate-a "${1:-round-1}" || status=3
./poc/linux/run-poc.sh candidate-b "${1:-round-1}" || status=3
exit "$status"
