"""校验单并发诊断前的真实会话探测结果。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def validate_probe(result_dir: Path, runner_exit: int) -> dict[str, Any]:
    """只在登录态和一条文章访问证据同时成立时放行。"""

    result_dir = result_dir.resolve()
    summary = json.loads((result_dir / "summary.json").read_text(encoding="utf-8"))
    login = json.loads((result_dir / "login-result.json").read_text(encoding="utf-8"))
    classes = summary.get("response_class_counts", {})
    if not isinstance(classes, dict):
        classes = {}
    ready = (
        runner_exit == 0
        and login.get("logged_in") is True
        and summary.get("input_count") == 1
        and summary.get("success_count") == 1
        and classes.get("post") == 1
    )
    return {
        "ready": ready,
        "runner_exit": runner_exit,
        "logged_in": login.get("logged_in") is True,
        "login_response_class": login.get("response_class"),
        "response_class_counts": classes,
        "result_dir": str(result_dir),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result-dir", type=Path, required=True)
    parser.add_argument("--runner-exit", type=int, required=True)
    args = parser.parse_args()
    try:
        evidence = validate_probe(args.result_dir, args.runner_exit)
    except (OSError, json.JSONDecodeError) as error:
        evidence = {
            "ready": False,
            "runner_exit": args.runner_exit,
            "error_category": type(error).__name__,
            "result_dir": str(args.result_dir.resolve()),
        }
    print(json.dumps(evidence, ensure_ascii=False, separators=(",", ":")))
    return 0 if evidence["ready"] is True else 5


if __name__ == "__main__":
    raise SystemExit(main())
