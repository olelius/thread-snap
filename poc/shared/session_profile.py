"""短信初始化浏览器资料目录的隔离准备与成功提升。"""

from __future__ import annotations

import shutil
from pathlib import Path


def prepare_isolated_profile(profile_dir: Path) -> Path:
    """重建本次初始化专用目录，不读取候选现有浏览器状态。"""

    profile_dir = profile_dir.resolve()
    if profile_dir.exists():
        shutil.rmtree(profile_dir)
    profile_dir.mkdir(parents=True, mode=0o700)
    return profile_dir


def promote_isolated_profile(source: Path, target: Path, backup: Path) -> None:
    """成功登录后替换候选资料目录；提升失败时恢复旧目录。"""

    source = source.resolve()
    target = target.resolve()
    backup = backup.resolve()
    if source == target or source == backup or target == backup:
        raise ValueError("会话资料目录必须彼此独立")
    if not source.is_dir() or not (source / "storage-state.json").is_file():
        raise ValueError("新会话资料缺少 storage-state.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    if backup.exists():
        shutil.rmtree(backup)
    had_target = target.exists()
    if had_target:
        target.replace(backup)
    try:
        source.replace(target)
    except Exception:
        if had_target and backup.exists() and not target.exists():
            backup.replace(target)
        raise
    if backup.exists():
        shutil.rmtree(backup)
