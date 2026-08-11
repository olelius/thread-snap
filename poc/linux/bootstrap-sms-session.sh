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
candidate_a_cdp_port="${THREADSNAP_CANDIDATE_A_CDP_PORT:-9222}"
candidate_b_cdp_port="${THREADSNAP_CANDIDATE_B_CDP_PORT:-9223}"

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

validate_cdp_port() {
  local port="$1"
  [[ "$port" =~ ^[0-9]+$ && "$port" -ge 1024 && "$port" -le 65535 ]] || {
    echo "ERROR: CDP 端口必须在 1024..65535" >&2
    return 2
  }
}

ensure_cdp_port_free() {
  local port="$1"
  if (echo > "/dev/tcp/127.0.0.1/$port") 2>/dev/null; then
    echo "ERROR: 回环 CDP 端口 $port 已被占用，请设置候选对应的 THREADSNAP_*_CDP_PORT 后重试" >&2
    return 2
  fi
}

print_manual_steps() {
  local candidate="$1"
  local port="$2"
  echo "manual_visual_verification=$candidate"
  echo "windows_tunnel=ssh -N -L $port:127.0.0.1:$port root@<服务器地址>"
  echo "windows_browser=chrome://inspect/#devices;configure=localhost:$port"
}

print_bootstrap_failure() {
  local candidate="$1"
  local result_path="$2"
  local exit_code="$3"
  local python="$ROOT/.runtime/candidate-a/bin/python"
  echo "sms_bootstrap_status=$candidate;status=failed;exit_code=$exit_code" >&2
  if [[ -x "$python" && -f "$result_path" ]]; then
    "$python" - "$candidate" "$result_path" <<'PY' >&2
import json
import sys
from pathlib import Path

candidate = sys.argv[1]
data = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
safe = {
    "candidate": candidate,
    "logged_in": data.get("logged_in") is True,
    "response_class": data.get("response_class"),
    "status": data.get("status"),
    "error_category": data.get("error_category"),
    "sms_page_ready": data.get("sms_page_ready") is True,
    "sms_request_clicked": data.get("sms_request_clicked") is True,
    "visual_verification_required": data.get("visual_verification_required") is True,
    "manual_verification_completed": data.get("manual_verification_completed") is True,
    "sms_send_confirmed": data.get("sms_send_confirmed") is True,
    "submitted": data.get("submitted") is True,
}
print("sms_bootstrap_evidence=" + json.dumps(safe, ensure_ascii=False, separators=(",", ":")))
PY
  else
    echo "sms_bootstrap_evidence=$candidate;result=missing" >&2
  fi
  echo "sms_bootstrap_result=$output_root" >&2
}

run_candidate_a() {
  local python="$ROOT/.runtime/candidate-a/bin/python"
  if [[ ! -x "$python" ]]; then
    echo "ERROR: 候选 A 运行环境尚未安装" >&2
    return 3
  fi
  echo "stage=candidate-a-sms-bootstrap"
  validate_cdp_port "$candidate_a_cdp_port"
  ensure_cdp_port_free "$candidate_a_cdp_port"
  print_manual_steps "candidate-a" "$candidate_a_cdp_port"
  set +e
  "$python" poc/candidate-a/src/throughput.py \
    --config "$config_path" \
    --output-dir "$output_root/candidate-a" \
    --bootstrap-sms \
    --manual-captcha-cdp-port "$candidate_a_cdp_port"
  local exit_code=$?
  set -e
  if [[ "$exit_code" -ne 0 ]]; then
    print_bootstrap_failure "candidate-a" "$output_root/candidate-a/sms-bootstrap-result.json" "$exit_code"
    return "$exit_code"
  fi
  echo "candidate-a-session=ready"
}

run_candidate_b() {
  if ! command -v npm >/dev/null; then
    echo "ERROR: 候选 B 运行环境尚未安装" >&2
    return 3
  fi
  echo "stage=candidate-b-sms-bootstrap"
  validate_cdp_port "$candidate_b_cdp_port"
  ensure_cdp_port_free "$candidate_b_cdp_port"
  print_manual_steps "candidate-b" "$candidate_b_cdp_port"
  set +e
  npm --prefix poc/candidate-b run throughput -- \
    --config "$config_path" \
    --output-dir "$output_root/candidate-b" \
    --bootstrap-sms \
    --manual-captcha-cdp-port "$candidate_b_cdp_port"
  local exit_code=$?
  set -e
  if [[ "$exit_code" -ne 0 ]]; then
    print_bootstrap_failure "candidate-b" "$output_root/candidate-b/sms-bootstrap-result.json" "$exit_code"
    return "$exit_code"
  fi
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
