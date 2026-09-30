"""独立备份恢复解包器：真实硬链接归档、校验与路径攻击验证。"""

from __future__ import annotations

import base64
import hashlib
import io
import os
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

RESTORE_SCRIPT = Path(__file__).resolve().parents[1] / "deploy/linux/restore-backup.sh"
EXTRACTOR = RESTORE_SCRIPT.read_text(encoding="utf-8").split("<<'PY'\n", 1)[1].split("\nPY\n", 1)[0]
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jGxkAAAAASUVORK5CYII="
)


class BackupArchiveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.archive = self.root / "backup.tar.gz"
        self.destination = self.root / "staging"
        self.destination.mkdir()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def extract(self) -> subprocess.CompletedProcess:
        """直接执行正式脚本的独立Python段，不导入应用或额外Python依赖。"""

        return subprocess.run(
            [sys.executable, "-c", EXTRACTOR, str(self.archive), str(self.destination)],
            capture_output=True, text=True, encoding="utf-8", timeout=20,
        )

    def build(self, entries, *, checksums: str | None = None) -> None:
        """构造真实tar成员；条目内容为文件bytes、链接目标str或空bytes。"""

        files = {name: value for name, kind, value in entries if kind == tarfile.REGTYPE}
        if checksums is None:
            paths = dict(files)
            for name, kind, value in entries:
                if kind == tarfile.LNKTYPE and value in files:
                    paths[name] = files[value]
            checksums = "".join(
                f"{hashlib.sha256(value).hexdigest()}  {name.removeprefix('backup/')}\n"
                for name, value in paths.items()
            )
        with tarfile.open(self.archive, "w:gz", dereference=False) as bundle:
            root = tarfile.TarInfo("backup")
            root.type = tarfile.DIRTYPE
            root.mode = 0o755
            bundle.addfile(root)
            for name, kind, value in entries:
                item = tarfile.TarInfo(name)
                item.type = kind
                item.mode = 0o755 if kind == tarfile.DIRTYPE else 0o644
                if kind == tarfile.REGTYPE:
                    item.size = len(value)
                    bundle.addfile(item, io.BytesIO(value))
                else:
                    if kind in {tarfile.LNKTYPE, tarfile.SYMTYPE}:
                        item.linkname = value
                    bundle.addfile(item)
            payload = checksums.encode("utf-8")
            item = tarfile.TarInfo("backup/SHA256SUMS")
            item.size = len(payload)
            item.mode = 0o644
            bundle.addfile(item, io.BytesIO(payload))

    def test_real_directory_tar_preserves_png_hardlink_and_independent_paths(self) -> None:
        source = self.root / "source" / "backup"
        original = source / "data/screenshots/evidence/page.png"
        tile = source / "data/screenshots/artifacts/tile.png"
        original.parent.mkdir(parents=True)
        tile.parent.mkdir(parents=True)
        original.write_bytes(PNG)
        os.link(original, tile)
        (source / "config").mkdir()
        (source / "config/threadsnap.env").write_text("THREADSNAP_DATA_DIR=/var/lib/threadsnap\n")
        # 嵌套同名校验文件也是业务文件，只有归档根SHA256SUMS排除自身。
        (source / "data/SHA256SUMS").write_text("nested business checksum\n")
        lines = [
            f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(source).as_posix()}\n"
            for path in sorted(source.rglob("*")) if path.is_file()
        ]
        (source / "SHA256SUMS").write_text("".join(lines), encoding="utf-8")
        with tarfile.open(self.archive, "w:gz", dereference=False) as bundle:
            bundle.add(source, arcname="backup")
        with tarfile.open(self.archive) as bundle:
            self.assertEqual(1, sum(member.islnk() for member in bundle.getmembers()))
        result = self.extract()
        self.assertEqual(0, result.returncode, result.stderr)
        restored_original = self.destination / "backup/data/screenshots/evidence/page.png"
        restored_tile = self.destination / "backup/data/screenshots/artifacts/tile.png"
        self.assertTrue(restored_original.samefile(restored_tile))
        self.assertEqual(PNG, restored_original.read_bytes())
        restored_original.unlink()
        self.assertEqual(PNG, restored_tile.read_bytes())
        self.assertEqual(PNG, original.read_bytes())
        self.assertEqual("backup", result.stdout.strip())

    def test_forward_hardlink_target_is_allowed_only_after_regular_file_written(self) -> None:
        self.build([
            ("backup/data/tile.png", tarfile.LNKTYPE, "backup/data/original.png"),
            ("backup/data/original.png", tarfile.REGTYPE, PNG),
        ])
        result = self.extract()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue((self.destination / "backup/data/tile.png").samefile(
            self.destination / "backup/data/original.png"
        ))

    def test_absolute_parent_backslash_drive_and_control_paths_are_rejected(self) -> None:
        names = (
            "/outside.png", "../outside.png", "backup/data/../../../outside.png",
            "C:/outside.png", "C:outside.png", "backup/data/C:outside.png",
            "backup\\..\\outside.png", "\\\\server\\share\\outside.png",
            "backup/data/bad\nname.png",
        )
        for name in names:
            with self.subTest(name=name):
                self.build([("backup/data/valid.png", tarfile.REGTYPE, PNG), (name, tarfile.REGTYPE, PNG)])
                result = self.extract()
                self.assertNotEqual(0, result.returncode)
                self.assertIn("unsafe backup path", result.stderr)
                self.assertEqual([], list(self.destination.iterdir()))

    def test_unsafe_hardlink_targets_are_rejected_before_any_extraction(self) -> None:
        targets = (
            "/outside.png", "../outside.png", "backup/../../outside.png", "C:/outside.png",
            "backup/data/C:outside.png", "backup\\data\\original.png", "backup/data/missing.png",
            "other/data/original.png", "backup/data/link.png", "backup/data",
        )
        for target in targets:
            with self.subTest(target=target):
                self.build([
                    ("backup/data", tarfile.DIRTYPE, b""),
                    ("backup/data/original.png", tarfile.REGTYPE, PNG),
                    ("backup/data/link.png", tarfile.LNKTYPE, target),
                ])
                result = self.extract()
                self.assertNotEqual(0, result.returncode)
                self.assertEqual([], list(self.destination.iterdir()))

    def test_hardlink_chain_is_rejected_even_when_ultimate_target_is_regular(self) -> None:
        self.build([
            ("backup/data/original.png", tarfile.REGTYPE, PNG),
            ("backup/data/first.png", tarfile.LNKTYPE, "backup/data/original.png"),
            ("backup/data/second.png", tarfile.LNKTYPE, "backup/data/first.png"),
        ])
        result = self.extract()
        self.assertNotEqual(0, result.returncode)
        self.assertIn("unsafe hardlink target", result.stderr)
        self.assertEqual([], list(self.destination.iterdir()))

    def test_duplicate_canonical_member_and_file_parent_are_rejected(self) -> None:
        for second in ("backup/data/file.png", "backup/data/./file.png", "backup/data//file.png", "backup/data/file.png/child"):
            with self.subTest(second=second):
                self.build([
                    ("backup/data/file.png", tarfile.REGTYPE, PNG),
                    (second, tarfile.REGTYPE, b"different"),
                ])
                result = self.extract()
                self.assertNotEqual(0, result.returncode)
                self.assertEqual([], list(self.destination.iterdir()))

    def test_symlinks_and_special_file_types_are_rejected(self) -> None:
        for kind in (tarfile.SYMTYPE, tarfile.FIFOTYPE, tarfile.CHRTYPE, tarfile.BLKTYPE, tarfile.CONTTYPE):
            with self.subTest(kind=kind):
                self.build([
                    ("backup/data/original.png", tarfile.REGTYPE, PNG),
                    ("backup/data/special", kind, "backup/data/original.png" if kind == tarfile.SYMTYPE else b""),
                ])
                result = self.extract()
                self.assertNotEqual(0, result.returncode)
                self.assertIn("unsafe backup member", result.stderr)
                self.assertEqual([], list(self.destination.iterdir()))

    def test_host_backup_entry_cannot_come_from_archive(self) -> None:
        for name, kind, value in (
            ("backup/data/backups", tarfile.DIRTYPE, b""),
            ("backup/data/backups/nested.tar.gz", tarfile.REGTYPE, b"backup"),
            ("backup/data/backups", tarfile.LNKTYPE, "backup/data/original.png"),
        ):
            with self.subTest(name=name, kind=kind):
                self.build([("backup/data/original.png", tarfile.REGTYPE, PNG), (name, kind, value)])
                result = self.extract()
                self.assertNotEqual(0, result.returncode)
                self.assertIn("host-owned recovery entry", result.stderr)
                self.assertEqual([], list(self.destination.iterdir()))

    def test_multiple_top_level_roots_are_rejected(self) -> None:
        self.build([
            ("backup/data/file.png", tarfile.REGTYPE, PNG),
            ("other/data/file.png", tarfile.REGTYPE, PNG),
        ])
        result = self.extract()
        self.assertNotEqual(0, result.returncode)
        self.assertIn("one top-level directory", result.stderr)

    def test_modified_file_fails_checksum(self) -> None:
        self.build([("backup/data/file.png", tarfile.REGTYPE, PNG)], checksums="0" * 64 + "  data/file.png\n")
        result = self.extract()
        self.assertNotEqual(0, result.returncode)
        self.assertIn("checksum invalid", result.stderr)

    def test_checksum_path_cannot_escape_root(self) -> None:
        for raw in ("/outside", "../outside", "C:/outside", "data\\file.png"):
            with self.subTest(raw=raw):
                # 校验失败可写临时解包区，但绝不向数据目录应用；每次换空临时区。
                self.destination = self.root / uuid_name(raw)
                self.destination.mkdir()
                self.build([("backup/data/file.png", tarfile.REGTYPE, PNG)], checksums="0" * 64 + f"  {raw}\n")
                result = self.extract()
                self.assertNotEqual(0, result.returncode)
                self.assertIn("unsafe backup path", result.stderr)

    def test_checksum_coverage_must_include_every_hardlink_path(self) -> None:
        self.build([
            ("backup/data/file.png", tarfile.REGTYPE, PNG),
            ("backup/data/link.png", tarfile.LNKTYPE, "backup/data/file.png"),
        ], checksums=hashlib.sha256(PNG).hexdigest() + "  data/file.png\n")
        result = self.extract()
        self.assertNotEqual(0, result.returncode)
        self.assertIn("does not cover every file", result.stderr)

    def test_preexisting_staging_files_are_never_overwritten(self) -> None:
        (self.destination / "sentinel").write_bytes(b"keep")
        self.build([("backup/data/file.png", tarfile.REGTYPE, PNG)])
        result = self.extract()
        self.assertNotEqual(0, result.returncode)
        self.assertIn("must be empty", result.stderr)
        self.assertEqual(b"keep", (self.destination / "sentinel").read_bytes())


def uuid_name(value: str) -> str:
    """仅供测试隔离目录命名，不把恶意路径直接用于本机文件操作。"""

    return hashlib.sha256(value.encode()).hexdigest()[:16]


if __name__ == "__main__":
    unittest.main()
