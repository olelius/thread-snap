#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

NODE_HOME="$ROOT/.runtime/node-v22.17.0-linux-x64"
export PATH="$NODE_HOME/bin:$PATH"
export PLAYWRIGHT_BROWSERS_PATH="$ROOT/.runtime/browsers"
export CRAWLEE_LOG_LEVEL="ERROR"

config_path="${THREADSNAP_CONFIG:-$ROOT/config.json}"
target="${1:-all}"
timestamp="$(date +%Y%m%dT%H%M%S%z)"
output_root="$ROOT/.runtime/sms-bootstrap/$timestamp"

if [[ ! -t 0 || ! -t 1 ]]; then
  echo "ERROR: 请直接在 SSH 交互终端运行本脚本" >&2
  exit 2
fi
if [[ ! -f "$config_path" ]]; then
  echo "ERROR: 缺少配置文件 $config_path" >&2
  exit 2
fi
if [[ "$target" != "all" && "$target" != "candidate-a" && "$target" != "candidate-b" ]]; then
  echo "用法: $0 [all|candidate-a|candidate-b]" >&2
  exit 2
fi

mkdir -p "$output_root"
chmod 700 "$output_root"

run_candidate_a() {
  local python="$ROOT/.runtime/candidate-a/bin/python"
  if [[ ! -x "$python" ]]; then
    echo "ERROR: 候选 A 运行环境尚未安装" >&2
    return 3
  fi
  echo "stage=candidate-a-sms-bootstrap"
  "$python" poc/candidate-a/src/throughput.py \
    --config "$config_path" \
    --output-dir "$output_root/candidate-a" \
    --bootstrap-sms
  echo "candidate-a-session=ready"
}

run_candidate_b() {
  if ! command -v npm >/dev/null; then
    echo "ERROR: 候选 B 运行环境尚未安装" >&2
    return 3
  fi
  echo "stage=candidate-b-sms-bootstrap"
  npm --prefix poc/candidate-b run throughput -- \
    --config "$config_path" \
    --output-dir "$output_root/candidate-b" \
    --bootstrap-sms
  echo "candidate-b-session=ready"
}

if [[ "$target" == "all" || "$target" == "candidate-a" ]]; then
  run_candidate_a
fi
if [[ "$target" == "all" || "$target" == "candidate-b" ]]; then
  run_candidate_b
fi

echo "sms_bootstrap_result=$output_root"
echo "next=./poc/linux/test-connectivity.sh"
