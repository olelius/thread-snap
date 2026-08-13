#!/usr/bin/env bash
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
source "$ROOT/poc/linux/process-control.sh"
trap 'stop_bounded_process' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

round_id="${1:-round-1}"
config_path="${THREADSNAP_CONFIG:-$ROOT/config.json}"
connectivity_input="${THREADSNAP_CONNECTIVITY_INPUT:-$ROOT/connectivity-urls.txt}"
python="$ROOT/.runtime/candidate-a/bin/python"

[[ -x "$python" ]] || { echo "ERROR: 请先运行 install.sh、start.sh 和 healthcheck.sh" >&2; exit 2; }
[[ -f "$ROOT/.runtime/ready" ]] || { echo "ERROR: 请先运行 start.sh" >&2; exit 2; }
[[ -f "$config_path" ]] || { echo "ERROR: 配置文件不存在: $config_path" >&2; exit 2; }
[[ -f "$connectivity_input" ]] || { echo "ERROR: 三条门禁清单不存在: $connectivity_input" >&2; exit 2; }
chmod 600 "$config_path"

if ! config_values="$("$python" - "$config_path" <<'PY'
import json
import math
import sys
from pathlib import Path

path = Path(sys.argv[1]).resolve()
config = json.loads(path.read_text(encoding="utf-8"))
candidate = config.get("candidate_a") or {}
input_path = (path.parent / str(config["input_file"])).resolve()
profile_dir = (path.parent / str(candidate.get("profile_dir", "profiles/candidate-a"))).resolve()
expected_count = int(config.get("expected_count", 2000))
window_seconds = int(config.get("window_seconds", 3600))
concurrency = int(candidate.get("content_api_concurrency", candidate.get("concurrency", 8)))
timeout_seconds = math.ceil(int(config.get("request_timeout_ms", 45000)) / 1000)
gate_count = int(candidate.get("content_api_gate_count", 3))
if expected_count < 1 or window_seconds < 1 or concurrency < 1 or timeout_seconds < 1:
    raise SystemExit("内容 API 配置数值必须为正整数")
if gate_count < 1 or gate_count > 3:
    raise SystemExit("candidate_a.content_api_gate_count 必须为 1..3")
print(input_path)
print(profile_dir / "storage-state.json")
print(expected_count)
print(window_seconds)
print(concurrency)
print(timeout_seconds)
print(gate_count)
PY
)"; then
  echo "ERROR: 内容 API 配置解析失败" >&2
  exit 2
fi
readarray -t values <<< "$config_values"
[[ "${#values[@]}" -eq 7 ]] || { echo "ERROR: 内容 API 配置解析结果不完整" >&2; exit 2; }
input_path="${values[0]}"
storage_state="${values[1]}"
expected_count="${values[2]}"
window_seconds="${values[3]}"
concurrency="${values[4]}"
timeout_seconds="${values[5]}"
gate_count="${values[6]}"

[[ -f "$input_path" ]] || { echo "ERROR: 2000条输入清单不存在: $input_path" >&2; exit 2; }
if [[ ! -f "$storage_state" ]]; then
  echo "ERROR: Candidate A Scrapling Session不存在: $storage_state" >&2
  echo "next=./poc/linux/bootstrap-sms-session.sh candidate-a" >&2
  exit 4
fi
chmod 600 "$storage_state"

timestamp="$(date +%Y%m%dT%H%M%S%z)"
result_parent="$ROOT/content-api-results"
result_dir="$result_parent/${round_id}-${timestamp}"
mkdir -p "$result_dir"

package_results() {
  local gate_exit="$1"
  local bulk_exit="$2"
  "$python" - "$result_dir" "$storage_state" "$gate_exit" "$bulk_exit" "$concurrency" "$expected_count" <<'PY'
import json
import os
import sys
from datetime import datetime
from pathlib import Path

result_dir = Path(sys.argv[1])
state = Path(sys.argv[2])
metadata = {
    "schema_version": "1.0",
    "mode": "candidate-a-content-api-linux",
    "generated_at": datetime.now().astimezone().isoformat(),
    "storage_state_present": state.is_file(),
    "storage_state_size": state.stat().st_size if state.is_file() else 0,
    "gate_exit": int(sys.argv[3]),
    "bulk_exit": int(sys.argv[4]),
    "concurrency": int(sys.argv[5]),
    "expected_count": int(sys.argv[6]),
}
(result_dir / "run-metadata.json").write_text(
    json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)
os.chmod(result_dir / "run-metadata.json", 0o600)
PY
  (cd "$result_dir" && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS)
  local archive="$result_parent/${round_id}-${timestamp}.tar.gz"
  tar -czf "$archive" -C "$result_parent" "${round_id}-${timestamp}"
  sha256sum "$archive" > "$archive.sha256"
  echo "result_dir=$result_dir"
  echo "result_archive=$archive"
  echo "copy_back=$archive $archive.sha256"
}

echo "stage=content-api-gate;count=$gate_count;concurrency=1"
set +e
run_bounded_process 300 15 "$python" poc/candidate-a/src/content_extraction.py \
  --input "$connectivity_input" \
  --storage-state "$storage_state" \
  --output-dir "$result_dir/gate" \
  --limit "$gate_count" \
  --concurrency 1 \
  --timeout-seconds "$timeout_seconds" > "$result_dir/gate.log" 2>&1
gate_exit=$?
set -e
if [[ "$gate_exit" -ne 0 ]]; then
  echo "content_api_gate=failed;exit=$gate_exit" >&2
  echo "next=检查 gate/summary.json；若为 login/captcha/challenge，运行 ./poc/linux/bootstrap-sms-session.sh candidate-a" >&2
  package_results "$gate_exit" 127
  exit "$gate_exit"
fi
echo "content_api_gate=passed"

echo "stage=content-api-bulk;count=$expected_count;concurrency=$concurrency"
hard_timeout_seconds=$((window_seconds + 120))
set +e
start_bounded_process "$hard_timeout_seconds" 15 "$python" poc/candidate-a/src/content_extraction.py \
  --input "$input_path" \
  --storage-state "$storage_state" \
  --output-dir "$result_dir/bulk" \
  --limit "$expected_count" \
  --concurrency "$concurrency" \
  --timeout-seconds "$timeout_seconds" > "$result_dir/bulk.log" 2>&1
start_exit=$?
if [[ "$start_exit" -ne 0 ]]; then
  set -e
  package_results "$gate_exit" "$start_exit"
  exit "$start_exit"
fi
runner_pid="$BOUNDED_RUNNER_PID"
./poc/linux/monitor-resources.sh "$runner_pid" "$result_dir/resource-metrics.csv" 2 &
monitor_pid=$!
wait_bounded_process
bulk_exit=$?
wait "$monitor_pid" 2>/dev/null || true
set -e

package_results "$gate_exit" "$bulk_exit"
if [[ "$bulk_exit" -eq 6 ]]; then
  echo "content_api_result=completed_with_partial_records" >&2
elif [[ "$bulk_exit" -eq 0 ]]; then
  echo "content_api_result=complete"
else
  echo "content_api_result=runner_failed;exit=$bulk_exit" >&2
fi
exit "$bulk_exit"
