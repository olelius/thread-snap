"""从本地明文配置生成最多三条样本的临时联通配置。"""

from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()

    config = json.loads(args.config.read_text(encoding="utf-8"))
    if not config.get("account") or not config.get("password"):
        raise ValueError("明文测试配置缺少账号或密码")
    urls = [line.strip() for line in args.input.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    if not 1 <= len(urls) <= 3:
        raise ValueError("联通样本数量必须为 1..3")
    if len(set(urls)) != len(urls):
        raise ValueError("联通样本包含重复 URL")

    prepared = copy.deepcopy(config)
    prepared["input_file"] = str(args.input.resolve())
    prepared["expected_count"] = len(urls)
    prepared["window_seconds"] = 300
    prepared["max_attempts"] = 1
    prepared["retry_delay_ms"] = 0
    prepared["capture_login_diagnostic"] = True
    prepared.setdefault("candidate_a", {})["concurrency"] = 1
    prepared["candidate_a"]["profile_dir"] = str((args.root / "profiles/connectivity-candidate-a").resolve())
    prepared.setdefault("candidate_b", {})["concurrency"] = 1
    prepared["candidate_b"]["profile_dir"] = str((args.root / "profiles/connectivity-candidate-b").resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(prepared, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        os.chmod(args.output, 0o600)
    except OSError:
        pass
    print(json.dumps({"sample_count": len(urls), "window_seconds": 300}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
