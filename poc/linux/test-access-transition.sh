#!/usr/bin/env bash
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
config_path="${THREADSNAP_CONFIG:-$ROOT/config.json}"
python="$ROOT/.runtime/candidate-a/bin/python"
timestamp="$(date +%Y%m%dT%H%M%S%z)"
bundle_dir="$ROOT/access-diagnostic-results/access-transition-$timestamp"
temp_config="$ROOT/.runtime/access-transition-$timestamp.json"
mkdir -p "$bundle_dir"
trap 'rm -f "$temp_config"' EXIT

[[ -x "$python" ]] || { echo "ERROR: 请先运行 install.sh 和 start.sh" >&2; exit 2; }
[[ -f "$config_path" ]] || { echo "ERROR: 配置文件不存在: $config_path" >&2; exit 2; }

"$python" - "$config_path" "$temp_config" <<'PY'
import json
import os
import sys
from pathlib import Path

source = Path(sys.argv[1]).resolve()
target = Path(sys.argv[2]).resolve()
config = json.loads(source.read_text(encoding="utf-8"))
base = source.parent
input_path = (base / config["input_file"]).resolve()
available = len([line for line in input_path.read_text(encoding="utf-8-sig").splitlines() if line.strip()])
config["input_file"] = str(input_path)
config["expected_count"] = min(500, available)
config["window_seconds"] = 1200
for key, default in (("candidate_a", "profiles/candidate-a"), ("candidate_b", "profiles/candidate-b")):
    value = config.setdefault(key, {})
    value["profile_dir"] = str((base / value.get("profile_dir", default)).resolve())
target.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
os.chmod(target, 0o600)
print(f"diagnostic_expected_count={config['expected_count']}")
print("diagnostic_window_seconds=1200")
PY

round_id="access-transition-$timestamp"
status=0

echo "stage=candidate-a-access-transition"
set +e
THREADSNAP_CONFIG="$temp_config" ./poc/linux/run-poc.sh candidate-a "$round_id" | tee "$bundle_dir/candidate-a.stdout.log"
candidate_a_exit=${PIPESTATUS[0]}
set -e
[[ "$candidate_a_exit" -eq 0 ]] || status=3

echo "stage=candidate-b-access-transition"
set +e
THREADSNAP_CONFIG="$temp_config" ./poc/linux/run-poc.sh candidate-b "$round_id" | tee "$bundle_dir/candidate-b.stdout.log"
candidate_b_exit=${PIPESTATUS[0]}
set -e
[[ "$candidate_b_exit" -eq 0 ]] || status=3

candidate_a_dir="$(sed -n 's/^result_dir=//p' "$bundle_dir/candidate-a.stdout.log" | tail -1)"
candidate_b_dir="$(sed -n 's/^result_dir=//p' "$bundle_dir/candidate-b.stdout.log" | tail -1)"
if [[ -z "$candidate_a_dir" || -z "$candidate_b_dir" ]]; then
  echo "ERROR: 候选结果目录缺失" >&2
  exit 3
fi

"$python" - "$bundle_dir/diagnostic-summary.json" "$candidate_a_dir" "$candidate_b_dir" "$candidate_a_exit" "$candidate_b_exit" <<'PY'
import json
import sys
from pathlib import Path

output = Path(sys.argv[1])
records = {}
for candidate, directory, exit_code in (
    ("candidate-a", Path(sys.argv[2]), int(sys.argv[4])),
    ("candidate-b", Path(sys.argv[3]), int(sys.argv[5])),
):
    summary = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
    diagnostics = [
        json.loads(line)
        for line in (directory / "access-diagnostics.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    records[candidate] = {
        "runner_exit": exit_code,
        "result_dir": str(directory),
        "success_count": summary.get("success_count"),
        "result_count": summary.get("result_count"),
        "response_class_counts": summary.get("response_class_counts", {}),
        "diagnostic_count": len(diagnostics),
        "diagnostic_triggers": [item.get("trigger") for item in diagnostics],
    }
output.write_text(json.dumps({"schema_version": "1.0", "candidates": records}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY

archive="$ROOT/access-diagnostic-results/access-transition-$timestamp.tar.gz"
relative_a="${candidate_a_dir#$ROOT/}"
relative_b="${candidate_b_dir#$ROOT/}"
relative_bundle="${bundle_dir#$ROOT/}"
tar -czf "$archive" -C "$ROOT" "$relative_a" "$relative_b" "$relative_bundle"
sha256sum "$archive" > "$archive.sha256"
echo "diagnostic_archive=$archive"
echo "copy_back=$archive $archive.sha256"
exit "$status"
