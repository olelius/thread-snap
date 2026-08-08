"""生成 Linux PoC 轮次的环境快照、时间指标和最终摘要。"""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
from datetime import datetime
from pathlib import Path


def command_output(command: list[str]) -> str | None:
    """执行只读环境命令，失败时返回空值而不中断结果收口。"""

    try:
        return subprocess.run(command, check=True, capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--result-dir", type=Path, required=True)
    parser.add_argument("--started-at", required=True)
    parser.add_argument("--ended-at", required=True)
    parser.add_argument("--window-seconds", type=int, required=True)
    parser.add_argument("--runner-exit", type=int, required=True)
    args = parser.parse_args()

    started = datetime.fromisoformat(args.started_at.replace("Z", "+00:00"))
    ended = datetime.fromisoformat(args.ended_at.replace("Z", "+00:00"))
    duration_seconds = (ended - started).total_seconds()
    runner_environment_path = args.result_dir / "runner-environment.json"
    runner_environment = (
        json.loads(runner_environment_path.read_text(encoding="utf-8"))
        if runner_environment_path.exists()
        else {}
    )
    environment = {
        "schema_version": "1.0",
        "candidate": args.candidate,
        "operating_system": platform.platform(),
        "machine": platform.machine(),
        "kernel": platform.release(),
        "libc": " ".join(platform.libc_ver()).strip() or None,
        "os_release": command_output(["sh", "-c", ". /etc/os-release 2>/dev/null; printf '%s %s' \"$ID\" \"$VERSION_ID\""]),
        "runner": runner_environment,
    }
    (args.result_dir / "environment.json").write_text(
        json.dumps(environment, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    summary_path = args.result_dir / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary.update(
        started_at=args.started_at,
        ended_at=args.ended_at,
        duration_seconds=duration_seconds,
        window_seconds=args.window_seconds,
        completed_within_window=duration_seconds <= args.window_seconds,
        runner_exit_code=args.runner_exit,
    )
    summary["passed"] = bool(summary.get("passed")) and summary["completed_within_window"] and args.runner_exit == 0
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary["passed"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
