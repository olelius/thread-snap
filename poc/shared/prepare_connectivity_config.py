"""从本地明文配置生成最多三条样本的临时联通配置。"""

from __future__ import annotations

import argparse
import copy
import json
import os
import shutil
from pathlib import Path


def resolve_profile_dir(config_path: Path, configured: object, default: str) -> Path:
    """按原始配置文件的位置解析候选会话目录。"""

    value = Path(str(configured or default))
    if not value.is_absolute():
        value = config_path.parent / value
    return value.resolve()


def refresh_connectivity_profile(source: Path, destination: Path) -> bool:
    """重建联通隔离目录，并只复制当前已认证的浏览器状态。"""

    source = source.resolve()
    destination = destination.resolve()
    source_state = source / "storage-state.json"
    destination_state = destination / "storage-state.json"

    if source == destination:
        return source_state.is_file()

    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True)
    if not source_state.is_file():
        return False

    shutil.copyfile(source_state, destination_state)
    try:
        os.chmod(destination_state, 0o600)
    except OSError:
        pass
    return True


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
    session_states: dict[str, bool] = {}
    for config_key, candidate_name in (("candidate_a", "candidate-a"), ("candidate_b", "candidate-b")):
        candidate = prepared.setdefault(config_key, {})
        source_profile = resolve_profile_dir(
            args.config.resolve(),
            candidate.get("profile_dir"),
            f"profiles/{candidate_name}",
        )
        connectivity_profile = (args.root / f"profiles/connectivity-{candidate_name}").resolve()
        session_states[candidate_name] = refresh_connectivity_profile(source_profile, connectivity_profile)
        candidate["concurrency"] = 1
        candidate["profile_dir"] = str(connectivity_profile)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(prepared, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        os.chmod(args.output, 0o600)
    except OSError:
        pass
    print(
        json.dumps(
            {
                "sample_count": len(urls),
                "window_seconds": 300,
                "session_state_copied": session_states,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
