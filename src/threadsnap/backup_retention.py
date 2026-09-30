"""运维权限下清理固定十四天旧备份，保护恢复点与发布回滚依赖。"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
import tarfile
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .retention import RETENTION_DAYS


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _files(path: Path) -> list[Path]:
    """备份组内部拒绝链接，避免越过已批准的备份根扫描或删除。"""
    entries = list(path.rglob("*")) if path.is_dir() else [path]
    if any(item.is_symlink() for item in entries):
        raise ValueError("备份组包含链接，需人工核对")
    return [item for item in entries if item.is_file()]


def _validated(path: Path, kind: str) -> bool:
    """SQLite恢复点执行quick_check，归档必须有匹配的SHA-256侧车。"""
    if kind == "sqlite":
        database = path / "threadsnap.db"
        wal = Path(str(database) + "-wal")
        if wal.exists() and wal.stat().st_size:
            return False  # 尚依赖在途WAL的目录不是已冻结的单文件恢复点。
        with closing(sqlite3.connect(
            database.as_uri() + "?mode=ro&immutable=1", uri=True
        )) as db:
            db.execute("PRAGMA query_only=ON")
            return db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    sidecar = Path(str(path) + ".sha256")
    if not sidecar.is_file() or sidecar.is_symlink():
        return False
    parts = sidecar.read_text(encoding="utf-8").strip().split(maxsplit=1)
    return (
        len(parts) == 2
        and bool(re.fullmatch(r"[a-fA-F0-9]{64}", parts[0]))
        and parts[1].lstrip("*") == path.name
        and _sha256(path) == parts[0].lower()
    )


def _archive_identity(path: Path) -> str:
    """只读取已校验归档的小型清单，不解压任何文件到磁盘。"""
    with tarfile.open(path, "r|gz") as archive:
        for member in archive:
            if Path(member.name).name != "backup-manifest.json":
                continue
            if not member.isfile() or member.size > 64 * 1024:
                raise ValueError("备份清单异常")
            stream = archive.extractfile(member)
            if stream is None:
                raise ValueError("备份清单不可读")
            with stream:
                manifest = json.load(stream)
            if not isinstance(manifest, dict) or not manifest.get("current_release"):
                raise ValueError("备份缺少发布身份")
            return str(manifest["current_release"])
    raise ValueError("归档不是已知的完整备份")


def prune_backups(
    data_dir: Path,
    *,
    app_root: Path = Path("/opt/threadsnap"),
    system_backup_root: Path = Path("/var/backups/threadsnap"),
    now: datetime | None = None,
    apply: bool = False,
) -> dict[str, Any]:
    """预览或删除已确认的旧备份组；业务数据、配置和离线安装包不在扫描范围。"""
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("备份保留时间必须带时区")
    cutoff = current.astimezone(timezone.utc) - timedelta(days=RETENTION_DAYS)
    # 不知道回滚指针时失败关闭，不能把故障安装现场的备份清空。
    release_names = []
    for name in ("current", "previous"):
        pointer = app_root / name
        if not pointer.is_dir():
            raise ValueError(f"缺少可用发布指针：{name}")
        release_names.append(pointer.resolve().name)
    pins = {
        value
        for release in release_names
        for suffix in [release.rsplit("-", 1)[-1]]
        for value in (release, suffix, suffix[:7])
        if len(value) >= 7
    }
    roots = {
        p.resolve() for p in (data_dir / "backups", system_backup_root) if p.is_dir()
    }
    if any(root == Path(root.anchor) or len(root.parts) < 3 for root in roots):
        raise ValueError("备份根不能是文件系统根或顶层系统目录")
    report: dict[str, Any] = {
        "cutoff": cutoff.isoformat(), "retention_days": RETENTION_DAYS,
        "eligible": [], "protected": [], "invalid": [], "removed": [], "errors": [],
    }
    candidates: list[dict[str, Any]] = []
    for root in sorted(roots):
        discovered = [(p.parent, "sqlite") for p in root.rglob("threadsnap.db")]
        discovered += [(p, "archive") for p in root.glob("threadsnap-backup-*.tar.gz")]
        for path, kind in discovered:
            if path == root or path.is_symlink() or not path.resolve().is_relative_to(root):
                report["invalid"].append({"path": str(path), "reason": "备份边界异常"})
                continue
            try:
                files = _files(path)
                if kind == "sqlite" and sum(p.name == "threadsnap.db" for p in files) != 1:
                    raise ValueError("嵌套备份组不能作为一个删除目标")
                if kind == "archive":
                    files.append(Path(str(path) + ".sha256"))
                if not files or not _validated(path, kind):
                    raise ValueError("备份完整性未通过")
                modified = max(p.stat().st_mtime_ns for p in files)
                # 只读取小型运维清单的发布身份；不输出内容或读取凭据。
                identity = str(path)
                if kind == "archive":
                    identity += " " + _archive_identity(path)
                if kind == "sqlite":
                    for manifest in path.glob("*.json"):
                        if manifest.stat().st_size > 64 * 1024:
                            continue
                        try:
                            data = json.loads(manifest.read_text(encoding="utf-8"))
                        except (ValueError, UnicodeError):
                            continue
                        if isinstance(data, dict):
                            identity += " " + " ".join(
                                str(data.get(key, ""))
                                for key in ("current_release", "release", "source_commit", "target_commit")
                            )
                candidates.append({
                    "path": str(path), "root": str(root), "kind": kind,
                    "mtime_ns": modified, "bytes": sum(p.stat().st_size for p in files),
                    "pinned": any(pin in identity for pin in pins),
                })
            except (OSError, ValueError, sqlite3.Error, tarfile.TarError) as exc:
                report["invalid"].append({"path": str(path), "reason": type(exc).__name__})
    # 完整归档与SQLite各保护一个最近可恢复点，避免只剩单独数据库不能恢复文件。
    newest = {
        max((item for item in candidates if item["kind"] == kind),
            key=lambda item: item["mtime_ns"])["path"]
        for kind in {item["kind"] for item in candidates}
    }
    for item in candidates:
        age = datetime.fromtimestamp(item["mtime_ns"] / 1e9, timezone.utc)
        reason = (
            "当前/回滚版本绑定" if item["pinned"] else
            "最近验证恢复点" if item["path"] in newest else
            "未到十四天" if age > cutoff else None
        )
        if reason:
            report["protected"].append({**item, "reason": reason})
            continue
        report["eligible"].append(item)
        if not apply:
            continue
        path, root = Path(item["path"]), Path(item["root"])
        try:
            # 执行前再次核对边界与修改时间；调用方还须持有运维备份互斥锁。
            files = _files(path)
            if item["kind"] == "archive":
                files.append(Path(str(path) + ".sha256"))
            if path.is_symlink() or not path.resolve().is_relative_to(root):
                raise ValueError("备份边界变化")
            if max(p.stat().st_mtime_ns for p in files) != item["mtime_ns"]:
                raise ValueError("备份执行期间发生变化")
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
                Path(str(path) + ".sha256").unlink(missing_ok=True)
            report["removed"].append(item["path"])
        except (OSError, ValueError) as exc:
            report["errors"].append({"path": str(path), "reason": type(exc).__name__})
    return report
