#!/usr/bin/env bash
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
candidate="${1:-}"
[[ "$candidate" == "candidate-a" || "$candidate" == "candidate-b" ]] || {
  echo "用法: $0 candidate-a|candidate-b" >&2
  exit 2
}
config_path="${THREADSNAP_CONFIG:-$ROOT/config.json}"
python="$ROOT/.runtime/candidate-a/bin/python"
timestamp="$(date +%Y%m%dT%H%M%S%z)"
bundle_parent="$ROOT/access-diagnostic-results"
bundle_dir="$bundle_parent/single-concurrency-$candidate-$timestamp"
temp_config="$ROOT/.runtime/single-concurrency-$candidate-$timestamp.json"
probe_config="$ROOT/.runtime/single-concurrency-probe-$candidate-$timestamp.json"
mkdir -p "$bundle_dir"
trap 'rm -f "$temp_config" "$probe_config"' EXIT

[[ -x "$python" ]] || { echo "ERROR: 请先运行 install.sh 和 start.sh" >&2; exit 2; }
[[ -f "$config_path" ]] || { echo "ERROR: 配置文件不存在: $config_path" >&2; exit 2; }

"$python" poc/shared/prepare_single_concurrency_config.py \
  --config "$config_path" \
  --output "$temp_config" \
  --candidate "$candidate" | tee "$bundle_dir/prepare.log"
prepare_exit=${PIPESTATUS[0]}
if [[ "$prepare_exit" -ne 0 ]]; then
  exit "$prepare_exit"
fi

"$python" - "$temp_config" "$probe_config" <<'PY'
import json
import os
import sys
from pathlib import Path

source = Path(sys.argv[1])
target = Path(sys.argv[2])
config = json.loads(source.read_text(encoding="utf-8"))
config["expected_count"] = 1
config["window_seconds"] = 180
target.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
os.chmod(target, 0o600)
PY

echo "stage=$candidate-session-probe"
set +e
THREADSNAP_CONFIG="$probe_config" ./poc/linux/run-poc.sh "$candidate" "single-concurrency-probe-$timestamp" \
  | tee "$bundle_dir/session-probe.stdout.log"
probe_runner_exit=${PIPESTATUS[0]}
set -e

probe_result_dir="$(sed -n 's/^result_dir=//p' "$bundle_dir/session-probe.stdout.log" | tail -1)"
if [[ -z "$probe_result_dir" || ! -d "$probe_result_dir" ]]; then
  echo "ERROR: 会话探测结果目录缺失" >&2
  exit 3
fi

set +e
probe_evidence="$("$python" poc/shared/validate_single_concurrency_probe.py \
  --result-dir "$probe_result_dir" \
  --runner-exit "$probe_runner_exit")"
probe_validation_exit=$?
set -e
echo "session_probe=$probe_evidence"
if [[ "$probe_validation_exit" -ne 0 ]]; then
  archive="$bundle_parent/single-concurrency-$candidate-$timestamp.tar.gz"
  relative_probe="${probe_result_dir#$ROOT/}"
  relative_bundle="${bundle_dir#$ROOT/}"
  tar -czf "$archive" -C "$ROOT" "$relative_probe" "$relative_bundle"
  sha256sum "$archive" > "$archive.sha256"
  echo "session_probe_result=login_required_or_probe_failed" >&2
  echo "next=./poc/linux/bootstrap-sms-session.sh $candidate" >&2
  echo "diagnostic_archive=$archive"
  echo "copy_back=$archive $archive.sha256"
  exit "$probe_validation_exit"
fi
echo "session_probe_result=ready;session_action=reuse_existing"

round_id="single-concurrency-$timestamp"
echo "stage=$candidate-single-concurrency"
set +e
THREADSNAP_CONFIG="$temp_config" ./poc/linux/run-poc.sh "$candidate" "$round_id" | tee "$bundle_dir/candidate.stdout.log"
runner_exit=${PIPESTATUS[0]}
set -e

result_dir="$(sed -n 's/^result_dir=//p' "$bundle_dir/candidate.stdout.log" | tail -1)"
if [[ -z "$result_dir" || ! -d "$result_dir" ]]; then
  echo "ERROR: 候选结果目录缺失" >&2
  exit 3
fi

"$python" - "$bundle_dir/diagnostic-summary.json" "$bundle_dir/prepare.log" "$result_dir" "$runner_exit" "$probe_result_dir" <<'PY'
import json
import sys
from pathlib import Path

output = Path(sys.argv[1])
prepare = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8").splitlines()[-1])
result_dir = Path(sys.argv[3])
runner_exit = int(sys.argv[4])
probe_result_dir = Path(sys.argv[5])
summary = json.loads((result_dir / "summary.json").read_text(encoding="utf-8"))
probe_summary = json.loads((probe_result_dir / "summary.json").read_text(encoding="utf-8"))
probe_login = json.loads((probe_result_dir / "login-result.json").read_text(encoding="utf-8"))
diagnostics = [
    json.loads(line)
    for line in (result_dir / "access-diagnostics.jsonl").read_text(encoding="utf-8").splitlines()
    if line.strip()
]
duration = float(summary.get("duration_seconds") or 0)
evidence = {
    "schema_version": "1.0",
    "diagnostic_kind": "validated-session-single-concurrency",
    "candidate": prepare["candidate"],
    "result_dir": str(result_dir),
    "runner_exit": runner_exit,
    "session_age_seconds_at_start": prepare["session_age_seconds"],
    "session_age_gate": prepare["session_age_gate"],
    "session_state_size": prepare["session_state_size"],
    "session_probe": {
        "result_dir": str(probe_result_dir),
        "logged_in": probe_login.get("logged_in") is True,
        "login_response_class": probe_login.get("response_class"),
        "success_count": probe_summary.get("success_count"),
        "response_class_counts": probe_summary.get("response_class_counts", {}),
    },
    "configured_concurrency": prepare["concurrency"],
    "input_count": summary.get("input_count"),
    "result_count": summary.get("result_count"),
    "success_count": summary.get("success_count"),
    "response_class_counts": summary.get("response_class_counts", {}),
    "duration_seconds": duration,
    "proportional_target_seconds": prepare["proportional_target_seconds"],
    "completed_within_proportional_target": bool(
        summary.get("result_count") == summary.get("input_count")
        and duration <= prepare["proportional_target_seconds"]
    ),
    "diagnostic_count": len(diagnostics),
    "diagnostic_triggers": [item.get("trigger") for item in diagnostics],
}
output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY

archive="$bundle_parent/single-concurrency-$candidate-$timestamp.tar.gz"
relative_result="${result_dir#$ROOT/}"
relative_probe="${probe_result_dir#$ROOT/}"
relative_bundle="${bundle_dir#$ROOT/}"
tar -czf "$archive" -C "$ROOT" "$relative_probe" "$relative_result" "$relative_bundle"
sha256sum "$archive" > "$archive.sha256"
echo "diagnostic_archive=$archive"
echo "copy_back=$archive $archive.sha256"
exit "$runner_exit"
