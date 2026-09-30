"""旧wheel回退的限定索引降级、失败补偿与业务数据保全。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from alembic.operations import Operations
from alembic.util import CommandError
from sqlalchemy import text

import threadsnap.db as database
from threadsnap.models import ExtractionRun

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "deploy/linux/rollback-release.sh").read_text(encoding="utf-8")
CODE = SCRIPT.split("<<'SCHEMA_PY'\n", 1)[1].split("\nSCHEMA_PY\n", 1)[0]
HELPERS = {"__name__": "rollback_schema_test_helpers"}
exec(compile(CODE, "rollback-release.sh:SCHEMA_PY", "exec"), HELPERS)
NEW = "d9e4b7a2c601"
OLD = "f3b6c9d2a804"


class RollbackSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.url = f"sqlite:///{(root / 'business.db').as_posix()}"
        self.migrations = Path(database.__file__).parent / "migrations"
        database.migrate_database(self.url)
        self.engine = database.build_engine(self.url)
        self.factory = database.build_session_factory(self.engine)
        with self.factory.begin() as db:
            db.add(ExtractionRun(
                id="preserved-business-run", number="preserved-business-run",
                trigger_type="manual", status="success", idempotency_key="preserve",
                request_hash="a" * 64, completed_count=1,
            ))
        self.assertEqual(NEW, self.revision(), "测试必须绑定已整合本次索引迁移的应用源码")

    def tearDown(self) -> None:
        self.engine.dispose()
        self.temporary.cleanup()

    def action(self, mode: str, target: str) -> str:
        return HELPERS["run_schema_action"](self.url, self.migrations, mode, target)

    def revision(self) -> str:
        return HELPERS["current_revision"](self.url)

    def indexes(self) -> set[str]:
        with self.engine.connect() as connection:
            return set(connection.scalars(text("SELECT name FROM sqlite_master WHERE type='index'")))

    def rows(self) -> list[tuple]:
        with self.engine.connect() as connection:
            return [tuple(row) for row in connection.execute(text("SELECT * FROM extraction_runs ORDER BY id"))]

    def test_exact_old_target_downgrades_six_indexes_and_recovers_new_business_writes(self) -> None:
        before, rows = self.indexes(), self.rows()
        self.assertEqual(f"{NEW}:downgrade", self.action("preflight", OLD))
        self.assertEqual(f"{OLD}:downgrade", self.action("downgrade", OLD))
        self.assertEqual(OLD, self.revision())
        self.assertEqual(6, len(before - self.indexes()))
        self.assertEqual(rows, self.rows())
        # 旧程序短暂开放后若验证失败，恢复只补索引，不能回写先前数据库抹掉业务。
        with self.engine.begin() as connection:
            connection.execute(text("UPDATE extraction_runs SET completed_count=7 WHERE id='preserved-business-run'"))
        latest = self.rows()
        self.assertEqual(f"{NEW}:recover", self.action("recover", NEW))
        self.assertEqual(NEW, self.revision())
        self.assertEqual(before, self.indexes())
        self.assertEqual(latest, self.rows())

    def test_unknown_revision_refuses_preflight_downgrade_and_recovery_without_writes(self) -> None:
        with self.engine.begin() as connection:
            connection.execute(text("UPDATE alembic_version SET version_num='unknown_revision'"))
        before, rows = self.indexes(), self.rows()
        for mode, target in (("preflight", OLD), ("downgrade", OLD), ("recover", NEW)):
            with self.subTest(mode=mode):
                with self.assertRaises((RuntimeError, CommandError)):
                    self.action(mode, target)
                self.assertEqual("unknown_revision", self.revision())
                self.assertEqual(before, self.indexes())
                self.assertEqual(rows, self.rows())

    def test_other_target_head_and_changed_revision_are_rejected(self) -> None:
        before, rows = self.indexes(), self.rows()
        with self.assertRaisesRegex(RuntimeError, "Incompatible"):
            self.action("preflight", "unrelated_target_head")
        with self.assertRaisesRegex(RuntimeError, "downgrade refused"):
            self.action("downgrade", NEW)
        self.assertEqual(before, self.indexes())
        self.assertEqual(rows, self.rows())
        self.action("downgrade", OLD)
        with self.assertRaisesRegex(RuntimeError, "downgrade refused"):
            self.action("downgrade", OLD)
        self.assertEqual(OLD, self.revision())

    def test_midway_drop_failure_rolls_back_ddl_and_revision_together(self) -> None:
        before, rows = self.indexes(), self.rows()
        original = Operations.drop_index
        calls = []

        def fail_after_drop(operation, name, *args, **kwargs):
            result = original(operation, name, *args, **kwargs)
            calls.append(name)
            if len(calls) == 1:
                raise RuntimeError("injected after first DROP INDEX")
            return result

        with patch.object(Operations, "drop_index", fail_after_drop):
            with self.assertRaisesRegex(RuntimeError, "injected"):
                self.action("downgrade", OLD)
        self.assertEqual(1, len(calls))
        self.assertEqual(NEW, self.revision())
        self.assertEqual(before, self.indexes())
        self.assertEqual(rows, self.rows())
        self.assertEqual(f"{NEW}:recover", self.action("recover", NEW))
        self.assertEqual(before, self.indexes())

    def test_recovery_at_new_revision_repairs_missing_index_without_replaying_history(self) -> None:
        before, rows = self.indexes(), self.rows()
        self.action("downgrade", OLD)
        new_index = sorted(before - self.indexes())[0]
        self.action("recover", NEW)
        with self.engine.begin() as connection:
            connection.exec_driver_sql(f'DROP INDEX "{new_index}"')
        self.assertEqual(NEW, self.revision())
        self.assertNotIn(new_index, self.indexes())
        self.action("recover", NEW)
        self.assertEqual(before, self.indexes())
        self.assertEqual(rows, self.rows())

    def test_matching_head_needs_no_migration_and_shell_recovers_before_service_start(self) -> None:
        before, rows = self.indexes(), self.rows()
        self.assertEqual(f"{NEW}:same", self.action("preflight", NEW))
        self.assertEqual(before, self.indexes())
        self.assertEqual(rows, self.rows())
        restore = SCRIPT.split("restore_current() {", 1)[1].split("\n}\n", 1)[0]
        self.assertLess(restore.index('schema_action recover "$schema_before"'), restore.index("systemctl start threadsnap.service"))
        self.assertIn("services remain stopped", restore)
        self.assertNotIn("from threadsnap.app import Container", SCRIPT)


if __name__ == "__main__":
    unittest.main()
