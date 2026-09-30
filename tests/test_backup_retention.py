"""固定14天运维备份保留与回滚恢复点保护。"""

import hashlib
import io
import json
import os
import sqlite3
import tarfile
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from threadsnap.backup_retention import prune_backups
from threadsnap.storage_activity import StorageProcessLock


class BackupRetentionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data = self.root / "data"
        self.backups = self.data / "backups"
        self.backups.mkdir(parents=True)
        self.app = self.root / "app"
        # 不依赖Windows创建目录符号链接的管理员权限；指针目录仍对应实际存在的恢复版本。
        (self.app / "current").mkdir(parents=True)
        (self.app / "previous").mkdir()
        self.now = datetime(2026, 9, 30, 4, tzinfo=timezone.utc)

    def tearDown(self):
        self.temp.cleanup()

    def database(self, name, age):
        path = self.backups / name
        path.mkdir(parents=True)
        with closing(sqlite3.connect(path / "threadsnap.db")) as db:
            db.execute("CREATE TABLE sample (value TEXT)")
            db.execute("INSERT INTO sample VALUES ('保留证据')")
            db.commit()
        stamp = (self.now - timedelta(days=age)).timestamp()
        os.utime(path / "threadsnap.db", (stamp, stamp))
        return path

    def run_policy(self, apply=False):
        return prune_backups(
            self.data, app_root=self.app, system_backup_root=self.root / "absent",
            now=self.now, apply=apply,
        )

    def test_boundary_pin_latest_and_repeat_are_safe(self):
        expired = self.database("old", 14)
        pinned = self.database("rollback-previous", 40)
        young = self.database("recent", 13)
        latest = self.database("newest", 1)
        preview = self.run_policy()
        self.assertEqual([str(expired)], [v["path"] for v in preview["eligible"]])
        self.assertTrue(expired.exists())
        result = self.run_policy(True)
        self.assertEqual([str(expired)], result["removed"])
        self.assertTrue(all(p.exists() for p in [pinned, young, latest]))
        self.assertEqual([], self.run_policy(True)["removed"])

    def test_only_restore_point_is_kept_even_if_old(self):
        path = self.database("only", 90)
        self.assertEqual([], self.run_policy(True)["removed"])
        self.assertTrue(path.exists())

    def test_unverified_database_and_nested_backup_parent_are_not_deleted(self):
        parent = self.database("nested", 30)
        child = self.database("nested/child", 40)
        self.database("latest", 1)
        broken = self.backups / "broken"
        broken.mkdir()
        (broken / "threadsnap.db").write_bytes(b"not sqlite")
        result = self.run_policy(True)
        self.assertTrue(parent.exists())
        self.assertTrue(broken.exists())
        self.assertFalse(child.exists())
        self.assertEqual(2, len(result["invalid"]))

    def test_archive_hash_and_embedded_rollback_identity(self):
        def archive(name, release, age):
            path = self.backups / f"threadsnap-backup-{name}.tar.gz"
            payload = json.dumps({"current_release": release}).encode()
            with tarfile.open(path, "w:gz") as package:
                entry = tarfile.TarInfo("backup/backup-manifest.json")
                entry.size = len(payload)
                package.addfile(entry, io.BytesIO(payload))
            sidecar = Path(str(path) + ".sha256")
            sidecar.write_text(hashlib.sha256(path.read_bytes()).hexdigest() + "  " + path.name)
            stamp = (self.now - timedelta(days=age)).timestamp()
            os.utime(path, (stamp, stamp))
            os.utime(sidecar, (stamp, stamp))
            return path

        old = archive("old", "unreferenced", 30)
        rollback = archive("rollback", str(self.app / "previous"), 40)
        newest = archive("latest", "unreferenced", 1)
        bad = archive("bad", "unreferenced", 30)
        bad.write_bytes(b"changed")
        result = self.run_policy(True)
        self.assertEqual([str(old)], result["removed"])
        self.assertTrue(rollback.exists() and newest.exists() and bad.exists())
        self.assertFalse(Path(str(old) + ".sha256").exists())

    def test_missing_rollback_pointer_fails_closed(self):
        (self.app / "previous").rmdir()
        with self.assertRaises(ValueError):
            self.run_policy(True)

    def test_process_lock_rejects_second_holder_then_releases(self):
        path = self.root / "application.lock"
        with StorageProcessLock(path):
            with self.assertRaises(RuntimeError):
                StorageProcessLock(path).acquire()
        with StorageProcessLock(path):
            pass

    def test_timer_is_fixed_and_enabled_only_after_release_verification(self):
        root = Path(__file__).resolve().parents[1]
        timer = (root / "deploy/linux/systemd/threadsnap-backup-retention.timer").read_text()
        self.assertIn("03:30:00 Asia/Shanghai", timer)
        self.assertIn("Persistent=true", timer)
        install = (root / "deploy/linux/install.sh").read_text(encoding="utf-8")
        self.assertGreater(
            install.index("systemctl enable --now threadsnap-backup-retention.timer"),
            install.index('if ! bash "$SCRIPT_DIR/verify.sh"'),
        )
        rollback = (root / "deploy/linux/rollback-release.sh").read_text(encoding="utf-8")
        self.assertLess(rollback.index("materialized_packages="), rollback.index(".current.rollback"))


if __name__ == "__main__":
    unittest.main()
