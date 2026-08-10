#!/usr/bin/env bash
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
config_path="${THREADSNAP_CONFIG:-$ROOT/config.json}"
input_path="${THREADSNAP_CONNECTIVITY_INPUT:-$ROOT/connectivity-urls.txt}"
timestamp="$(date +%Y%m%dT%H%M%S%z)"
result_parent="$ROOT/connectivity-results"
result_dir="$result_parent/connectivity-$timestamp"
temp_dir="$ROOT/.runtime/connectivity-$timestamp"
temp_config="$temp_dir/config.json"
mkdir -p "$result_dir/candidate-a" "$result_dir/candidate-b" "$temp_dir"
trap 'rm -f "$temp_config"' EXIT

python="$ROOT/.runtime/candidate-a/bin/python"
if [[ ! -x "$python" ]]; then python="$(command -v python3 || true)"; fi
if [[ -z "$python" ]]; then
  printf '{"schema_version":"1.0","ready_for_2000":false,"next_action":"install_python_3_11_or_newer"}\n' > "$result_dir/connectivity-summary.json"
  archive="$result_parent/connectivity-$timestamp.tar.gz"
  tar -czf "$archive" -C "$result_parent" "connectivity-$timestamp"
  sha256sum "$archive" > "$archive.sha256"
  echo "result_archive=$archive"
  echo "copy_back=$archive $archive.sha256"
  exit 3
fi

for candidate in candidate-a candidate-b; do
  : > "$result_dir/$candidate/url-results.jsonl"
  : > "$result_dir/$candidate/request-events.jsonl"
  printf '{"schema_version":"1.0","candidate":"%s","logged_in":false,"status":"runner_not_started"}\n' "$candidate" > "$result_dir/$candidate/login-result.json"
done

./poc/linux/preflight.sh > "$result_dir/preflight.log" 2>&1
preflight_exit=$?
./poc/linux/healthcheck.sh > "$result_dir/healthcheck.log" 2>&1
healthcheck_exit=$?

prepare_exit=0
"$python" poc/shared/prepare_connectivity_config.py \
  --config "$config_path" \
  --input "$input_path" \
  --output "$temp_config" \
  --root "$ROOT" > "$result_dir/prepare.log" 2>&1 || prepare_exit=$?

if [[ -f "$input_path" ]]; then
  cp "$input_path" "$result_dir/input-urls.txt"
else
  : > "$result_dir/input-urls.txt"
fi
sample_count="$(grep -cve '^[[:space:]]*$' "$result_dir/input-urls.txt" || true)"

network_exit=127
if [[ "$sample_count" -ge 1 ]]; then
  "$python" poc/shared/network_probe.py \
    --input "$result_dir/input-urls.txt" \
    --output "$result_dir/network.json" > "$result_dir/network.log" 2>&1
  network_exit=$?
else
  printf '{"schema_version":"1.0","transport_ready":false,"error_category":"missing_connectivity_input"}\n' > "$result_dir/network.json"
  : > "$result_dir/network.log"
fi

candidate_a_exit=127
if [[ "$prepare_exit" -eq 0 && -x "$ROOT/.runtime/candidate-a/bin/python" ]]; then
  "$ROOT/.runtime/candidate-a/bin/python" poc/candidate-a/src/throughput.py \
    --config "$temp_config" \
    --output-dir "$result_dir/candidate-a" > "$result_dir/candidate-a/run.log" 2>&1
  candidate_a_exit=$?
else
  printf 'candidate A runtime or temporary configuration is not ready\n' > "$result_dir/candidate-a/run.log"
fi

NODE_HOME="$ROOT/.runtime/node-v22.17.0-linux-x64"
export PATH="$NODE_HOME/bin:$PATH"
export PLAYWRIGHT_BROWSERS_PATH="$ROOT/.runtime/browsers"
candidate_b_exit=127
if [[ "$prepare_exit" -eq 0 ]] && command -v npm >/dev/null; then
  npm --prefix poc/candidate-b run throughput -- \
    --config "$temp_config" \
    --output-dir "$result_dir/candidate-b" > "$result_dir/candidate-b/run.log" 2>&1
  candidate_b_exit=$?
else
  printf 'candidate B runtime or temporary configuration is not ready\n' > "$result_dir/candidate-b/run.log"
fi

for candidate in candidate-a candidate-b; do
  "$python" poc/shared/validate_results.py \
    --input-list "$result_dir/input-urls.txt" \
    --results "$result_dir/$candidate/url-results.jsonl" \
    --candidate "$candidate" \
    --expected-count "$sample_count" \
    --summary "$result_dir/$candidate/summary.json" >> "$result_dir/$candidate/run.log" 2>&1 || true
done

"$python" poc/shared/finalize_connectivity.py \
  --result-dir "$result_dir" \
  --preflight-exit "$preflight_exit" \
  --healthcheck-exit "$healthcheck_exit" \
  --network-exit "$network_exit" \
  --candidate-a-exit "$candidate_a_exit" \
  --candidate-b-exit "$candidate_b_exit" > "$result_dir/finalize.log" 2>&1
finalize_exit=$?

rm -rf "$result_dir/candidate-b/crawlee-storage"
(cd "$result_dir" && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS)
mkdir -p "$result_parent"
archive="$result_parent/connectivity-$timestamp.tar.gz"
tar -czf "$archive" -C "$result_parent" "connectivity-$timestamp"
sha256sum "$archive" > "$archive.sha256"
echo "result_dir=$result_dir"
echo "result_archive=$archive"
echo "copy_back=$archive $archive.sha256"
exit "$finalize_exit"
