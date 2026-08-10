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
mkdir -p "$bundle_dir"
trap 'rm -f "$temp_config"' EXIT

[[ -x "$python" ]] || { echo "ERROR: 请先运行 install.sh 和 start.sh" >&2; exit 2; }
[[ -f "$config_path" ]] || { echo "ERROR: 配置文件不存在: $config_path" >&2; exit 2; }

"$python" poc/shared/prepare_single_concurrency_config.py \
  --config "$config_path" \
  --output "$temp_config" \
  --candidate "$candidate" | tee "$bundle_dir/prepare.log"
prepare_exit=${PIPESTATUS[0]}
if [[ "$prepare_exit" -ne 0 ]]; then
  echo "next=./poc/linux/bootstrap-sms-session.sh $candidate" >&2
  exit "$prepare_exit"
fi

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

"$python" - "$bundle_dir/diagnostic-summary.json" "$bundle_dir/prepare.log" "$result_dir" "$runner_exit" <<'PY'
import json
import sys
from pathlib import Path

output = Path(sys.argv[1])
prepare = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8").splitlines()[-1])
result_dir = Path(sys.argv[3])
runner_exit = int(sys.argv[4])
summary = json.loads((result_dir / "summary.json").read_text(encoding="utf-8"))
diagnostics = [
    json.loads(line)
    for line in (result_dir / "access-diagnostics.jsonl").read_text(encoding="utf-8").splitlines()
    if line.strip()
]
duration = float(summary.get("duration_seconds") or 0)
evidence = {
    "schema_version": "1.0",
    "diagnostic_kind": "fresh-session-single-concurrency",
    "candidate": prepare["candidate"],
    "result_dir": str(result_dir),
    "runner_exit": runner_exit,
    "session_age_seconds_at_start": prepare["session_age_seconds"],
    "session_state_size": prepare["session_state_size"],
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
relative_bundle="${bundle_dir#$ROOT/}"
tar -czf "$archive" -C "$ROOT" "$relative_result" "$relative_bundle"
sha256sum "$archive" > "$archive.sha256"
echo "diagnostic_archive=$archive"
echo "copy_back=$archive $archive.sha256"
exit "$runner_exit"
