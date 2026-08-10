"""为 fresh-session 单并发诊断生成隔离配置。"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

VALID_CANDIDATES = {"candidate-a": ("candidate_a", "profiles/candidate-a"), "candidate-b": ("candidate_b", "profiles/candidate-b")}
DIAGNOSTIC_COUNT = 500
DIAGNOSTIC_WINDOW_SECONDS = 2_400
PROPORTIONAL_TARGET_SECONDS = 900
SESSION_MAX_AGE_SECONDS = 1_800


def _resolve(base: Path, value: str) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (base / path).resolve()


def prepare_config(
    *,
    source: Path,
    target: Path,
    candidate: str,
    now_epoch: float | None = None,
) -> dict[str, Any]:
    """校验刚初始化的候选会话，并生成单并发500条诊断配置。"""

    if candidate not in VALID_CANDIDATES:
        raise ValueError("candidate 必须是 candidate-a 或 candidate-b")
    source = source.resolve()
    target = target.resolve()
    config = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("配置根节点必须是对象")
    base = source.parent
    input_value = config.get("input_file")
    if not isinstance(input_value, str) or not input_value.strip():
        raise ValueError("input_file 必须是非空字符串")
    input_path = _resolve(base, input_value)
    if not input_path.is_file():
        raise ValueError(f"输入清单不存在: {input_path}")
    available = sum(1 for line in input_path.read_text(encoding="utf-8-sig").splitlines() if line.strip())
    if available < 1:
        raise ValueError("输入清单没有有效 URL")

    config_key, default_profile = VALID_CANDIDATES[candidate]
    candidate_config = config.setdefault(config_key, {})
    if not isinstance(candidate_config, dict):
        raise ValueError(f"{config_key} 必须是对象")
    profile_value = candidate_config.get("profile_dir", default_profile)
    if not isinstance(profile_value, str) or not profile_value.strip():
        raise ValueError(f"{config_key}.profile_dir 必须是非空字符串")
    profile_dir = _resolve(base, profile_value)
    storage_state = profile_dir / "storage-state.json"
    if not storage_state.is_file() or storage_state.stat().st_size == 0:
        raise ValueError(f"候选会话状态缺失，请先初始化: {candidate}")
    now = time.time() if now_epoch is None else now_epoch
    session_age_seconds = max(0, int(now - storage_state.stat().st_mtime))
    if session_age_seconds > SESSION_MAX_AGE_SECONDS:
        raise ValueError(
            f"候选会话状态已超过 {SESSION_MAX_AGE_SECONDS} 秒，请重新初始化: {candidate}"
        )

    config["input_file"] = str(input_path)
    config["expected_count"] = min(DIAGNOSTIC_COUNT, available)
    config["window_seconds"] = DIAGNOSTIC_WINDOW_SECONDS
    candidate_config["profile_dir"] = str(profile_dir)
    candidate_config["concurrency"] = 1
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(target, 0o600)
    return {
        "schema_version": "1.0",
        "candidate": candidate,
        "expected_count": config["expected_count"],
        "concurrency": 1,
        "window_seconds": DIAGNOSTIC_WINDOW_SECONDS,
        "proportional_target_seconds": PROPORTIONAL_TARGET_SECONDS,
        "session_max_age_seconds": SESSION_MAX_AGE_SECONDS,
        "session_age_seconds": session_age_seconds,
        "session_state_size": storage_state.stat().st_size,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--candidate", choices=sorted(VALID_CANDIDATES), required=True)
    args = parser.parse_args()
    try:
        evidence = prepare_config(source=args.config, target=args.output, candidate=args.candidate)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}")
        return 2
    print(json.dumps(evidence, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
