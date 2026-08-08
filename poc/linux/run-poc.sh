#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
candidate="${1:-}"
round_id="${2:-round-1}"
config_path="${THREADSNAP_CONFIG:-$ROOT/config.json}"
[[ "$candidate" == "candidate-a" || "$candidate" == "candidate-b" ]] || { echo "用法: $0 candidate-a|candidate-b [round-id]" >&2; exit 2; }
[[ -f "$config_path" ]] || { echo "ERROR: 配置文件不存在: $config_path" >&2; exit 2; }
[[ -f .runtime/ready ]] || { echo "ERROR: 请先运行 install.sh、start.sh 和 healthcheck.sh" >&2; exit 2; }
chmod 600 "$config_path"

python="$ROOT/.runtime/candidate-a/bin/python"
NODE_HOME="$ROOT/.runtime/node-v22.17.0-linux-x64"
export PATH="$NODE_HOME/bin:$PATH"
export PLAYWRIGHT_BROWSERS_PATH="$ROOT/.runtime/browsers"

readarray -t values < <("$python" - "$config_path" <<'PY'
import json, sys
from pathlib import Path
p = Path(sys.argv[1]).resolve()
c = json.loads(p.read_text(encoding="utf-8"))
print((p.parent / c["input_file"]).resolve())
print(c["expected_count"])
print(c["window_seconds"])
PY
)
input_path="${values[0]}"
expected_count="${values[1]}"
window_seconds="${values[2]}"
timestamp="$(date +%Y%m%dT%H%M%S%z)"
result_dir="$ROOT/results/$candidate/${round_id}-${timestamp}"
mkdir -p "$result_dir"
head -n "$expected_count" "$input_path" > "$result_dir/input-urls.txt"
: > "$result_dir/run.log"
: > "$result_dir/url-results.jsonl"
: > "$result_dir/request-events.jsonl"
printf '{"schema_version":"1.0","candidate":"%s","logged_in":false,"status":"runner_not_started"}\n' "$candidate" > "$result_dir/login-result.json"

started_at="$(date --iso-8601=seconds)"
if [[ "$candidate" == "candidate-a" ]]; then
  "$python" poc/candidate-a/src/throughput.py --config "$config_path" --output-dir "$result_dir" >> "$result_dir/run.log" 2>&1 &
else
  npm --prefix poc/candidate-b run throughput -- --config "$config_path" --output-dir "$result_dir" >> "$result_dir/run.log" 2>&1 &
fi
runner_pid=$!
./poc/linux/monitor-resources.sh "$runner_pid" "$result_dir/resource-metrics.csv" 5 &
monitor_pid=$!
set +e
wait "$runner_pid"
runner_exit=$?
wait "$monitor_pid" 2>/dev/null || true
set -e
ended_at="$(date --iso-8601=seconds)"

set +e
"$python" poc/shared/validate_results.py \
  --input-list "$result_dir/input-urls.txt" \
  --results "$result_dir/url-results.jsonl" \
  --candidate "$candidate" \
  --expected-count "$expected_count" \
  --summary "$result_dir/summary.json" >> "$result_dir/run.log" 2>&1
validator_exit=$?

"$python" poc/shared/finalize_run.py \
  --candidate "$candidate" \
  --result-dir "$result_dir" \
  --started-at "$started_at" \
  --ended-at "$ended_at" \
  --window-seconds "$window_seconds" \
  --runner-exit "$runner_exit" >> "$result_dir/run.log" 2>&1
finalize_exit=$?
set -e

rm -rf "$result_dir/crawlee-storage" "$result_dir/runner-environment.json"
(cd "$result_dir" && sha256sum environment.json summary.json login-result.json input-urls.txt url-results.jsonl request-events.jsonl resource-metrics.csv run.log > SHA256SUMS)
echo "result_dir=$result_dir"
if [[ "$runner_exit" -ne 0 || "$validator_exit" -ne 0 || "$finalize_exit" -ne 0 ]]; then
  exit 3
fi
