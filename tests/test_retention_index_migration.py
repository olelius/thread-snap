"""六项保留级联索引的真实 Alembic 升降级、数据不变与查询路径回归。"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

from alembic import command
from alembic.config import Config

from threadsnap import models
from threadsnap.db import build_engine, build_session_factory

BASE_REVISION = "f3b6c9d2a804"
INDEX_REVISION = "d9e4b7a2c601"
EXPECTED_INDEXES = (
    ("ix_comment_snapshots_post", "comment_snapshots", "post_id"),
    ("ix_sentiment_analysis_reused_from", "sentiment_analyses", "reused_from_analysis_id"),
    (
        "ix_manual_sentiment_inherited_from",
        "manual_sentiment_revisions",
        "inherited_from_revision_id",
    ),
    ("ix_evidence_item_post_snapshot", "circle_page_evidence_items", "post_snapshot_id"),
    ("ix_artifact_item_post_snapshot", "screenshot_artifact_items", "post_snapshot_id"),
    ("ix_post_snapshots_run", "post_snapshots", "run_id"),
)


class RetentionIndexMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "migration.sqlite"
        self.url = f"sqlite:///{self.path.as_posix()}"
        self.config = Config()
        self.config.set_main_option(
            "script_location", str(Path(models.__file__).parent / "migrations")
        )
        self.config.attributes["database_url"] = self.url
        command.upgrade(self.config, BASE_REVISION)
        self.engine = build_engine(self.url)
        self.factory = build_session_factory(self.engine)
        self._seed_references()

    def tearDown(self) -> None:
        self.engine.dispose()
        self.temporary.cleanup()

    def _seed_references(self) -> None:
        """建立评论、分析复用、人工继承、页面及成果对帖子的真实外键关系。"""
        with self.factory.begin() as db:
            for key in ("old", "kept"):
                db.add(
                    models.ExtractionRun(
                        id=key,
                        number=key,
                        trigger_type="manual",
                        idempotency_key=key,
                        request_hash="a" * 64,
                        status="success",
                    )
                )
            db.flush()
            for key in ("old", "kept"):
                db.add(
                    models.CircleTask(
                        id="task-" + key,
                        run_id=key,
                        platform_code="dongchedi",
                        external_id=key,
                        circle_url="https://example.test/" + key,
                        queue_sequence=1,
                        target_count=1,
                        status="success",
                    )
                )
            db.flush()
            for key in ("old", "kept"):
                db.add(
                    models.PostSnapshot(
                        id="post-" + key,
                        run_id=key,
                        circle_task_id="task-" + key,
                        platform_post_id=key,
                        url="https://example.test/post/" + key,
                        order_index=0,
                    )
                )
            db.flush()
            for key in ("old", "kept"):
                db.add(
                    models.CommentSnapshot(
                        id="comment-" + key,
                        post_id="post-" + key,
                        content="保留原文",
                        order_index=0,
                    )
                )
                db.add(
                    models.SentimentAnalysis(
                        id="analysis-" + key,
                        post_id="post-" + key,
                        platform_code="dongchedi",
                        platform_post_id=key,
                        input_hash=key,
                        status="analysis_success",
                        config_revision=1,
                        subject_version=1,
                        model_code="fixture",
                    )
                )
                db.add(
                    models.ManualSentimentRevision(
                        id="revision-" + key, post_id="post-" + key, action="set", result="negative"
                    )
                )
            db.flush()
            db.get(
                models.SentimentAnalysis, "analysis-kept"
            ).reused_from_analysis_id = "analysis-old"
            db.get(
                models.ManualSentimentRevision, "revision-kept"
            ).inherited_from_revision_id = "revision-old"
            db.add(
                models.CirclePageEvidence(
                    id="page",
                    run_id="old",
                    circle_task_id="task-old",
                    page_number=1,
                    exact_url="https://example.test/old",
                    adapter_version="fixture",
                    browser_version="fixture",
                    viewport_width=2,
                    viewport_height=1,
                    document_width=2,
                    document_height=1,
                    screenshot_path="fixture.png",
                    screenshot_sha256="a" * 64,
                    manifest_path="fixture.json",
                    manifest_sha256="b" * 64,
                )
            )
            db.add(
                models.ScreenshotArtifactGroup(
                    id="group",
                    chain_root_run_id="old",
                    platform_code="dongchedi",
                    external_id="old",
                    section="dynamic",
                    list_order="latest_reply",
                )
            )
            db.flush()
            db.add(
                models.CirclePageEvidenceItem(
                    id="page-item",
                    evidence_id="page",
                    circle_task_id="task-old",
                    post_snapshot_id="post-old",
                    platform_post_id="old",
                    url="https://example.test/post/old",
                    source_position=0,
                    x=0,
                    y=0,
                    width=2,
                    height=1,
                    text_sha256="c" * 64,
                )
            )
            db.add(
                models.ScreenshotArtifactVersion(
                    id="version",
                    group_id="group",
                    version=1,
                    reason="fixture",
                    input_sha256="d" * 64,
                    item_count=1,
                    negative_count=0,
                    package_path="fixture.zip",
                    package_sha256="e" * 64,
                )
            )
            db.flush()
            db.add(
                models.ScreenshotArtifactItem(
                    id="artifact-item",
                    version_id="version",
                    post_snapshot_id="post-old",
                    platform_post_id="old",
                    sentiment_result="negative",
                    contribution_run_number="old",
                    captured_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
                    tile_index=0,
                    y=0,
                    height=1,
                )
            )

    def _snapshot(self) -> dict:
        """除迁移版本外，对每张表的定义、全部行及外键逐项比较。"""
        with closing(sqlite3.connect(self.path)) as db:
            tables = db.execute(
                "SELECT name, sql FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' AND name != 'alembic_version' ORDER BY name"
            ).fetchall()
            return {
                name: {
                    "ddl": ddl,
                    "rows": db.execute(f'SELECT * FROM "{name}" ORDER BY rowid').fetchall(),
                    "foreign_keys": db.execute(f'PRAGMA foreign_key_list("{name}")').fetchall(),
                }
                for name, ddl in tables
            }

    def _indexes(self) -> set[str]:
        with closing(sqlite3.connect(self.path)) as db:
            return {
                row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='index'")
            }

    def test_upgrade_and_downgrade_only_change_exact_six_indexes(self) -> None:
        before = self._snapshot()
        base_indexes = self._indexes()
        command.upgrade(self.config, INDEX_REVISION)
        self.assertEqual(self._snapshot(), before)
        self.assertEqual(self._indexes() - base_indexes, {name for name, _, _ in EXPECTED_INDEXES})
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(
                db.execute("SELECT version_num FROM alembic_version").fetchone()[0], INDEX_REVISION
            )
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
        command.downgrade(self.config, BASE_REVISION)
        self.assertEqual(self._snapshot(), before)
        self.assertEqual(self._indexes(), base_indexes)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(
                db.execute("SELECT version_num FROM alembic_version").fetchone()[0], BASE_REVISION
            )
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
        # 实际回退后还可再升级同一数据库；重复 head 不追加额外索引。
        command.upgrade(self.config, "head")
        command.upgrade(self.config, "head")
        self.assertEqual(self._snapshot(), before)
        self.assertEqual(self._indexes() - base_indexes, {name for name, _, _ in EXPECTED_INDEXES})

    def test_six_fk_lookups_use_left_prefix_and_models_match(self) -> None:
        command.upgrade(self.config, INDEX_REVISION)
        with closing(sqlite3.connect(self.path)) as db:
            for name, table, column in EXPECTED_INDEXES:
                with self.subTest(index=name):
                    index = next(
                        index
                        for index in models.Base.metadata.tables[table].indexes
                        if index.name == name
                    )
                    self.assertFalse(index.unique)
                    self.assertEqual([value.name for value in index.columns], [column])
                    metadata = next(
                        row for row in db.execute(f'PRAGMA index_list("{table}")') if row[1] == name
                    )
                    self.assertEqual(metadata[2], 0, "不能增加唯一性约束")
                    self.assertEqual(
                        [row[2] for row in db.execute(f'PRAGMA index_info("{name}")')], [column]
                    )
                    plan = " ".join(
                        row[3]
                        for row in db.execute(
                            f'EXPLAIN QUERY PLAN SELECT rowid FROM "{table}" WHERE "{column}"=?',
                            ("lookup",),
                        )
                    )
                    self.assertIn("SEARCH", plan)
                    self.assertIn(name, plan)
                    self.assertNotIn("SCAN", plan)

    def test_partial_ddl_upgrade_and_downgrade_resume_without_rewriting_data(self) -> None:
        """模拟SQLite部分DDL已提交但revision未推进，只补缺项；回退也可继续。"""
        before = self._snapshot()
        base_indexes = self._indexes()
        command.upgrade(self.config, INDEX_REVISION)
        missing = EXPECTED_INDEXES[-1][0]
        with closing(sqlite3.connect(self.path)) as db:
            db.execute(f'DROP INDEX "{missing}"')
            db.execute("UPDATE alembic_version SET version_num=?", (BASE_REVISION,))
            db.commit()
        self.assertEqual(len(self._indexes() - base_indexes), 5)
        command.upgrade(self.config, INDEX_REVISION)
        command.upgrade(self.config, INDEX_REVISION)
        self.assertEqual(self._indexes() - base_indexes, {name for name, _, _ in EXPECTED_INDEXES})
        self.assertEqual(self._snapshot(), before)
        with closing(sqlite3.connect(self.path)) as db:
            db.execute(f'DROP INDEX "{missing}"')
            db.commit()
        command.downgrade(self.config, BASE_REVISION)
        command.downgrade(self.config, BASE_REVISION)
        self.assertEqual(self._indexes(), base_indexes)
        self.assertEqual(self._snapshot(), before)

    def test_conflicting_named_index_does_not_get_silently_accepted_or_removed(self) -> None:
        name, table, column = EXPECTED_INDEXES[0]
        before = self._snapshot()
        variants = (
            f'CREATE UNIQUE INDEX "{name}" ON "{table}"("{column}")',
            f'CREATE INDEX "{name}" ON post_snapshots(run_id)',
            f'CREATE INDEX "{name}" ON "{table}"("{column}") WHERE "{column}" IS NOT NULL',
        )
        for statement in variants:
            with self.subTest(ddl=statement):
                with closing(sqlite3.connect(self.path)) as db:
                    db.execute(statement)
                    db.commit()
                with self.assertRaisesRegex(RuntimeError, "索引定义冲突"):
                    command.upgrade(self.config, INDEX_REVISION)
                self.assertIn(name, self._indexes())
                self.assertEqual(self._snapshot(), before)
                with closing(sqlite3.connect(self.path)) as db:
                    self.assertEqual(
                        db.execute("SELECT version_num FROM alembic_version").fetchone()[0],
                        BASE_REVISION,
                    )
                    db.execute("UPDATE alembic_version SET version_num=?", (INDEX_REVISION,))
                    db.commit()
                with self.assertRaisesRegex(RuntimeError, "索引定义冲突"):
                    command.downgrade(self.config, BASE_REVISION)
                self.assertIn(name, self._indexes())
                self.assertEqual(self._snapshot(), before)
                with closing(sqlite3.connect(self.path)) as db:
                    db.execute("UPDATE alembic_version SET version_num=?", (BASE_REVISION,))
                    db.execute(f'DROP INDEX "{name}"')
                    db.commit()

    def test_indexed_delete_preserves_cascade_and_set_null_semantics(self) -> None:
        command.upgrade(self.config, INDEX_REVISION)
        with self.factory.begin() as db:
            db.delete(db.get(models.PostSnapshot, "post-old"))
        with self.factory() as db:
            for model, identity in (
                (models.CommentSnapshot, "comment-old"),
                (models.SentimentAnalysis, "analysis-old"),
                (models.ManualSentimentRevision, "revision-old"),
            ):
                self.assertIsNone(db.get(model, identity))
            self.assertIsNone(
                db.get(models.SentimentAnalysis, "analysis-kept").reused_from_analysis_id
            )
            self.assertIsNone(
                db.get(models.ManualSentimentRevision, "revision-kept").inherited_from_revision_id
            )
            self.assertIsNone(db.get(models.CirclePageEvidenceItem, "page-item").post_snapshot_id)
            self.assertIsNone(
                db.get(models.ScreenshotArtifactItem, "artifact-item").post_snapshot_id
            )
            self.assertEqual(db.get(models.CommentSnapshot, "comment-kept").content, "保留原文")
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_offline_range_emits_only_standard_index_ddl_without_inspection(self) -> None:
        """离线生成明确只输出六项DDL，不读取目标库或伪装成幂等修复。"""
        before = self._snapshot()
        output = StringIO()
        self.config.output_buffer = output
        command.upgrade(self.config, f"{BASE_REVISION}:{INDEX_REVISION}", sql=True)
        sql = output.getvalue()
        self.assertEqual(sql.count("CREATE INDEX "), 6)
        self.assertNotIn("IF NOT EXISTS", sql)
        output.truncate(0)
        output.seek(0)
        command.downgrade(self.config, f"{INDEX_REVISION}:{BASE_REVISION}", sql=True)
        self.assertEqual(output.getvalue().count("DROP INDEX "), 6)
        self.assertEqual(self._snapshot(), before)


if __name__ == "__main__":
    unittest.main()
