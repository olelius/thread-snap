"""十四天整链过期的真实 SQLite、文件系统和失败恢复合同。"""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import func, select, text

from threadsnap.config import Settings
from threadsnap.db import Base, build_engine, build_session_factory
from threadsnap.models import (
    CirclePageEvidence,
    CircleTask,
    CommentSnapshot,
    ExtractionRun,
    ManualSentimentRevision,
    PostSnapshot,
    ReputationDeleteJob,
    ReputationResult,
    ReputationRun,
    ReputationScheduleEvent,
    ReputationTombstone,
    ScreenshotArtifactContribution,
    ScreenshotArtifactGroup,
    SentimentAnalysis,
)
from threadsnap.reputation import ReputationService
from threadsnap.retention import RetentionService
from threadsnap.screenshots import ScreenshotService
from threadsnap.services import RunService
from threadsnap.storage_activity import StorageActivity


class RetentionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.settings = Settings(
            data_dir=root / "data",
            database_url=f"sqlite:///{root / 'test.db'}",
            start_background_services=False,
        )
        self.settings.ensure_directories()
        self.engine = build_engine(self.settings.database_url)
        Base.metadata.create_all(self.engine)
        self.factory = build_session_factory(self.engine)
        self.activity = StorageActivity()
        self.runs = RunService(self.factory)
        self.screenshots = ScreenshotService(self.factory, self.settings)
        self.reputation = ReputationService(self.factory, self.settings)
        self.now = datetime(2030, 1, 30, 6, tzinfo=timezone.utc)
        self.old = self.now - timedelta(days=15)
        self.events = []
        self.service = self.make_service()

    def tearDown(self):
        self.engine.dispose()
        self.temporary.cleanup()

    def make_service(self):
        return RetentionService(
            self.factory,
            self.settings,
            self.runs,
            self.screenshots,
            self.reputation,
            self.activity,
            event_publisher=lambda *args: self.events.append(args),
        )

    def test_expired_reuse_origins_do_not_change_retained_sentiment_or_image(self):
        """来源引用可置空，但保留批次的AI/人工结论和既有成果文件必须独立成立。"""
        self.extraction("origin")
        recent = self.now - timedelta(days=1)
        self.extraction("kept", finish=recent)
        self.group("kept-group", ["kept"])
        picture = self.settings.screenshot_artifact_dir / "kept-group/old.png"
        before = picture.read_bytes()
        with self.factory.begin() as db:
            for name, moment in (("origin", self.old), ("kept", recent)):
                post = db.get(PostSnapshot, f"post-{name}")
                post.analysis_status = "analysis_completed"
                post.sentiment_result = "negative"
                post.sentiment_source = "inherited_manual" if name == "kept" else "manual"
                post.sentiment_updated_at = moment
                db.add(SentimentAnalysis(
                    id=f"ai-{name}", post_id=post.id, platform_code="dongchedi",
                    platform_post_id="same-post", input_hash="a" * 64,
                    status="analysis_completed", config_revision=1, subject_version=1,
                    model_code="test", result="negative", summary="冻结负面结论",
                    created_at=moment, finished_at=moment,
                ))
                db.add(ManualSentimentRevision(
                    id=f"manual-{name}", post_id=post.id, action="set", result="negative",
                    note="冻结人工结论", created_at=moment,
                ))
            db.flush()
            db.get(SentimentAnalysis, "ai-kept").reused_from_analysis_id = "ai-origin"
            db.get(ManualSentimentRevision, "manual-kept").inherited_from_revision_id = "manual-origin"
        outcome = self.service.process_once(self.now, force=True)
        self.assertEqual(["origin"], outcome["completed"])
        with self.factory() as db:
            post = db.get(PostSnapshot, "post-kept")
            self.assertEqual(("negative", "inherited_manual"),
                             (post.sentiment_result, post.sentiment_source))
            analysis = db.get(SentimentAnalysis, "ai-kept")
            self.assertEqual(("negative", "冻结负面结论"), (analysis.result, analysis.summary))
            self.assertIsNone(analysis.reused_from_analysis_id)
            manual = db.get(ManualSentimentRevision, "manual-kept")
            self.assertEqual(("negative", "冻结人工结论"), (manual.result, manual.note))
            self.assertIsNone(manual.inherited_from_revision_id)
        self.assertEqual(before, picture.read_bytes())

    def extraction(self, name, *, finish=None, parent=None, status="success"):
        finish = finish or self.old
        with self.factory.begin() as db:
            run = ExtractionRun(
                id=name,
                number=name,
                trigger_type="manual",
                status=status,
                idempotency_key=name,
                request_hash="a" * 64,
                related_run_id=parent,
                created_at=finish,
                finished_at=finish,
            )
            db.add(run)
            db.flush()
            task = CircleTask(
                id=f"task-{name}",
                run_id=name,
                platform_code="dongchedi",
                external_id="1",
                circle_url="https://example.test/circle/1",
                status=status,
                queue_sequence=1,
                target_count=1,
                created_at=finish,
                finished_at=finish,
            )
            db.add(task)
            db.flush()
            post = PostSnapshot(
                id=f"post-{name}",
                run_id=name,
                circle_task_id=task.id,
                platform_post_id=name,
                url=f"https://example.test/post/{name}",
                order_index=0,
                created_at=finish,
            )
            db.add(post)
        for root in (self.settings.screenshot_evidence_dir, self.settings.export_dir):
            directory = root / name
            directory.mkdir()
            (directory / "frozen.bin").write_bytes(b"immutable")
        return name

    def group(self, name, run_ids):
        with self.factory.begin() as db:
            db.add(
                ScreenshotArtifactGroup(
                    id=name,
                    chain_root_run_id=run_ids[0],
                    platform_code="dongchedi",
                    external_id="1",
                    section="dynamic",
                    list_order="latest_reply",
                    status="waiting_for_sentiment",
                    dirty=True,
                )
            )
            db.flush()
            for run_id in run_ids:
                db.add(
                    ScreenshotArtifactContribution(
                        group_id=name, run_id=run_id, circle_task_id=f"task-{run_id}"
                    )
                )
        directory = self.settings.screenshot_artifact_dir / name
        directory.mkdir()
        (directory / "old.png").write_bytes(b"frozen-artifact")

    def reputation_run(
        self, name, *, source="scheduled", parent=None, finish=None, status="success", key=...
    ):
        finish = finish or self.old
        if key is ...:
            key = f"reputation:{finish.date().isoformat()}:daily" if source == "scheduled" else name
        with self.factory.begin() as db:
            db.add(
                ReputationRun(
                    id=name,
                    number=name,
                    source_type=source,
                    run_type="daily",
                    schedule_type="daily",
                    planned_date=finish.date().isoformat(),
                    idempotency_key=key,
                    # 与正式 _ensure_official_run 相同：根自指，补跑引用正式根。
                    root_run_id=parent or (name if source == "scheduled" else None),
                    status=status,
                    created_at=finish,
                    started_at=finish,
                    finished_at=finish,
                    report_status="success",
                )
            )
        directory = self.settings.reputation_dir / name
        directory.mkdir()
        (directory / "region.png").write_bytes(b"reputation-evidence")
        return name

    def test_exact_fourteen_days_and_read_only_preview(self):
        boundary = self.now - timedelta(days=14)
        self.extraction("root", finish=boundary)
        before = self.service.preview(self.now - timedelta(microseconds=1))
        self.assertEqual(before["eligible"], [])
        eligible = self.service.preview(self.now)["eligible"]
        self.assertEqual([x["root_id"] for x in eligible], ["root"])
        self.assertFalse(self.service.root.exists())
        self.assertTrue(
            all(str(self.settings.data_dir.resolve()) in p for p in eligible[0]["paths"])
        )

    def test_recent_child_and_manual_decision_extend_whole_chain(self):
        self.extraction("root")
        self.extraction("child", parent="root", finish=self.now - timedelta(days=1))
        self.assertEqual(self.service.preview(self.now)["eligible"], [])
        with self.factory.begin() as db:
            db.get(ExtractionRun, "child").finished_at = self.old
            db.add(
                ManualSentimentRevision(
                    post_id="post-root",
                    action="set",
                    result="negative",
                    created_at=self.now - timedelta(days=2),
                )
            )
        self.assertEqual(self.service.preview(self.now)["eligible"], [])
        with self.factory.begin() as db:
            revision = db.scalar(select(ManualSentimentRevision))
            revision.created_at = self.old
        self.assertEqual(len(self.service.preview(self.now)["eligible"]), 1)

    def test_nonterminal_child_and_missing_completion_time_are_never_expired(self):
        self.extraction("root")
        self.extraction("child", parent="root", status="queued")
        self.assertEqual(self.service.preview(self.now)["eligible"], [])
        with self.factory.begin() as db:
            child = db.get(ExtractionRun, "child")
            child.status = "success"
            child.finished_at = None
        self.assertEqual(self.service.preview(self.now)["eligible"], [])
        with self.factory() as db:
            self.assertIsNotNone(db.get(ExtractionRun, "root"))

    def test_whole_chain_cascade_and_historical_dirty_does_not_pin(self):
        self.extraction("root")
        self.extraction("child", parent="root")
        self.extraction("retained", finish=self.now)
        self.group("group", ["root", "child"])
        with self.factory.begin() as db:
            db.add(CommentSnapshot(post_id="post-child", content="comment", order_index=0))
            db.add(ManualSentimentRevision(post_id="post-root", action="set", created_at=self.old))
        result = self.service.process_once(self.now, force=True)
        self.assertEqual(result["status"], "complete", result)
        with self.factory() as db:
            self.assertEqual(list(db.scalars(select(ExtractionRun.id))), ["retained"])
            self.assertEqual(db.scalar(select(func.count()).select_from(CommentSnapshot)), 0)
            self.assertEqual(
                db.scalar(select(func.count()).select_from(ManualSentimentRevision)), 0
            )
            self.assertEqual(
                db.scalar(select(func.count()).select_from(ScreenshotArtifactGroup)), 0
            )
            self.assertEqual(db.execute(text("PRAGMA foreign_key_check")).all(), [])
        self.assertFalse((self.settings.screenshot_artifact_dir / "group").exists())
        self.assertFalse((self.settings.screenshot_evidence_dir / "root").exists())
        self.assertTrue((self.settings.export_dir / "retained/frozen.bin").exists())
        self.assertEqual(set(self.events), {("run.deleted", "root"), ("run.deleted", "child")})

    def test_busy_lease_defers_and_can_resume_same_day(self):
        self.extraction("root")
        with self.activity.use() as acquired:
            self.assertTrue(acquired)
            result = self.service.process_once(self.now)
        self.assertEqual(result["status"], "busy")
        self.assertFalse(self.service.root.exists())
        self.assertEqual(self.service.process_once(self.now)["status"], "complete")
        self.assertEqual(self.service.process_once(self.now)["status"], "not_due")

    def test_only_after_beijing_three_and_restart_uses_daily_marker(self):
        self.extraction("root")
        before = self.now.replace(hour=18) - timedelta(days=1)  # 北京时间次日02:00
        self.assertEqual(self.service.process_once(before)["status"], "not_due")
        self.assertEqual(self.service.process_once(self.now)["status"], "complete")
        self.assertEqual(self.make_service().process_once(self.now)["status"], "not_due")

    def test_file_failure_keeps_durable_intent_and_restart_cleans(self):
        self.extraction("root")
        with patch.object(
            self.service, "_remove_paths", side_effect=PermissionError("test failure")
        ):
            result = self.service.process_once(self.now, force=True)
        self.assertEqual(result["status"], "partial_failure")
        with self.factory() as db:
            self.assertIsNone(db.get(ExtractionRun, "root"))
        self.assertEqual(len(list(self.service.root.glob("extraction-*.json"))), 1)
        self.assertTrue((self.settings.export_dir / "root/frozen.bin").exists())
        result = self.make_service().process_once(self.now, force=True)
        self.assertEqual(result["status"], "complete", result)
        self.assertFalse((self.settings.export_dir / "root").exists())
        self.assertEqual(list(self.service.root.glob("extraction-*.json")), [])

    def test_precommit_failure_rechecks_before_retry(self):
        self.extraction("root")
        with patch.object(self.runs, "delete_chain", side_effect=RuntimeError("before commit")):
            result = self.service.process_once(self.now, force=True)
        self.assertEqual(result["status"], "partial_failure")
        with self.factory.begin() as db:
            db.add(ManualSentimentRevision(post_id="post-root", action="set", created_at=self.now))
        self.assertEqual(
            self.make_service().process_once(self.now, force=True)["status"], "complete"
        )
        with self.factory() as db:
            self.assertIsNotNone(db.get(ExtractionRun, "root"))
        self.assertTrue((self.settings.export_dir / "root/frozen.bin").exists())
        self.assertEqual(list(self.service.root.glob("extraction-*.json")), [])

    def test_crash_after_database_commit_recovers_and_repeated_cleanup_is_safe(self):
        self.extraction("root")
        original = self.runs.delete_chain

        def committed_then_crashed(*args):
            original(*args)
            raise RuntimeError("process interrupted after commit")

        with patch.object(self.runs, "delete_chain", side_effect=committed_then_crashed):
            result = self.service.process_once(self.now, force=True)
        self.assertEqual(result["status"], "partial_failure")
        self.assertTrue((self.settings.export_dir / "root/frozen.bin").exists())
        self.assertEqual(
            self.make_service().process_once(self.now, force=True)["status"], "complete"
        )
        self.assertEqual(self.make_service().process_once(self.now, force=True)["completed"], [])

    def test_database_group_failure_rolls_back_entire_chain(self):
        self.extraction("root")
        self.extraction("child", parent="root")
        self.group("group", ["root", "child"])
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE TRIGGER fail_delete BEFORE DELETE ON screenshot_artifact_groups "
                    "BEGIN SELECT RAISE(FAIL, 'test rollback'); END"
                )
            )
        self.assertEqual(
            self.service.process_once(self.now, force=True)["status"], "partial_failure"
        )
        with self.factory() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(ExtractionRun)), 2)
            self.assertEqual(db.get(ExtractionRun, "child").related_run_id, "root")
            self.assertEqual(db.scalar(select(func.count()).select_from(PostSnapshot)), 2)
        with self.engine.begin() as conn:
            conn.execute(text("DROP TRIGGER fail_delete"))
        self.assertEqual(
            self.make_service().process_once(self.now, force=True)["status"], "complete"
        )

    def test_path_outside_chain_is_not_deleted(self):
        self.extraction("root")
        outside = self.settings.data_dir / "keep.png"
        outside.write_bytes(b"keep")
        with self.factory.begin() as db:
            db.add(
                CirclePageEvidence(
                    run_id="root",
                    circle_task_id="task-root",
                    page_number=1,
                    exact_url="https://example.test",
                    adapter_version="test",
                    browser_version="test",
                    viewport_width=1,
                    viewport_height=1,
                    document_width=1,
                    document_height=1,
                    screenshot_path=str(outside),
                    screenshot_sha256="a" * 64,
                    manifest_path=str(outside),
                    manifest_sha256="a" * 64,
                )
            )
        self.assertEqual(self.service.preview(self.now)["skipped"][0]["reason"], "unsafe_path")
        self.assertEqual(
            self.service.process_once(self.now, force=True)["status"], "partial_failure"
        )
        self.assertEqual(outside.read_bytes(), b"keep")

    def test_tampered_pending_plan_does_not_delete_outside(self):
        self.extraction("root")
        with patch.object(self.service, "_remove_paths", side_effect=OSError("disk")):
            self.service.process_once(self.now, force=True)
        plan_path = next(self.service.root.glob("extraction-*.json"))
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        plan["paths"] = [str(self.settings.data_dir)]
        plan_path.write_text(json.dumps(plan), encoding="utf-8")
        result = self.make_service().process_once(self.now, force=True)
        self.assertEqual(result["status"], "partial_failure")
        self.assertTrue((self.settings.export_dir / "root/frozen.bin").exists())

    def test_running_analysis_and_shared_group_are_protected(self):
        self.extraction("root")
        self.extraction("recent", finish=self.now)
        with self.factory.begin() as db:
            db.add(
                SentimentAnalysis(
                    post_id="post-root",
                    platform_code="dongchedi",
                    platform_post_id="root",
                    input_hash="a",
                    status="analysis_running",
                    config_revision=1,
                    subject_version=1,
                    model_code="test",
                    created_at=self.old,
                )
            )
        self.assertEqual(
            self.service.preview(self.now)["skipped"][0]["reason"], "analysis_in_progress"
        )
        self.group("shared", ["root", "recent"])
        self.assertEqual(
            self.service.preview(self.now)["skipped"][0]["reason"], "shared_artifact_group"
        )

    def test_reputation_chain_tombstone_baseline_and_non_scheduled(self):
        self.reputation_run("old-root")
        self.reputation_run("retry", source="retry", parent="old-root")
        self.reputation_run("accepted", source="real_acceptance")
        self.reputation_run("synthetic", source="synthetic")
        self.reputation_run("recent", finish=self.now)
        baseline = {"vehicle|dongchedi": {"metrics": {"score": "4.5"}, "source_run_id": "old-root"}}
        with self.factory.begin() as db:
            run = db.get(ReputationRun, "recent")
            run.baseline_source_run_id = "old-root"
            run.baseline_snapshot = baseline
            db.add(
                ReputationScheduleEvent(
                    planned_date=self.old.date().isoformat(),
                    run_type="daily",
                    planned_at=self.old,
                    run_id="old-root",
                    status="success",
                    message="scheduled",
                )
            )
            db.add(
                ReputationResult(
                    run_id="old-root",
                    vehicle_id="vehicle",
                    series_name="s",
                    vehicle_name="v",
                    role="focus",
                    role_position=0,
                    vehicle_position=0,
                    platform_code="dongchedi",
                    platform_name="懂车帝",
                    status="success",
                    collected_at=self.old,
                )
            )
        result = self.service.process_once(self.now, force=True)
        self.assertEqual(result["status"], "complete", result)
        with self.factory() as db:
            self.assertEqual(list(db.scalars(select(ReputationRun.id))), ["recent"])
            self.assertEqual(db.get(ReputationRun, "recent").baseline_snapshot, baseline)
            self.assertEqual(db.scalar(select(func.count()).select_from(ReputationTombstone)), 1)
            event = db.scalar(select(ReputationScheduleEvent))
            self.assertEqual(event.status, "deleted")
            self.assertIsNone(event.run_id)
            self.assertEqual(db.execute(text("PRAGMA foreign_key_check")).all(), [])
        self.assertIsNone(self.reputation._ensure_official_run(self.old, self.old))
        self.assertEqual(self.reputation.delete_official("old-root")["status"], "success")
        self.assertEqual(list((self.settings.reputation_dir / ".quarantine").iterdir()), [])
        self.assertFalse((self.settings.reputation_dir / "retry").exists())

    def test_reputation_self_root_retry_boundary_and_frozen_baseline(self):
        """真实自指根与补跑归为一链；子ID先排序时也不能误认根或改写保留基线。"""
        boundary = self.now - timedelta(days=14)
        self.reputation_run("z-root")
        self.reputation_run("a-retry", source="retry", parent="z-root", finish=boundary)
        self.reputation_run("retained", finish=self.now)
        baseline = {
            "vehicle|dongchedi": {
                "metrics": {"score": {"raw": "4.5", "value": "4.5"}},
                "source_run_id": "a-retry",
            }
        }
        with self.factory.begin() as db:
            self.assertEqual(db.get(ReputationRun, "z-root").root_run_id, "z-root")
            retained = db.get(ReputationRun, "retained")
            retained.baseline_source_run_id = "z-root"
            retained.baseline_snapshot = baseline
        self.assertEqual(self.service.preview(self.now - timedelta(microseconds=1))["eligible"], [])
        eligible = self.service.preview(self.now)["eligible"]
        self.assertEqual(len(eligible), 1)
        self.assertEqual(eligible[0]["root_id"], "z-root")
        self.assertEqual(eligible[0]["run_ids"], ["a-retry", "z-root"])
        self.assertEqual(eligible[0]["expires_at"], self.now.isoformat())
        result = self.service.process_once(self.now, force=True)
        self.assertEqual(result["status"], "complete", result)
        self.assertEqual(result["completed"], ["z-root"])
        with self.factory() as db:
            self.assertEqual(list(db.scalars(select(ReputationRun.id))), ["retained"])
            self.assertEqual(db.get(ReputationRun, "retained").baseline_snapshot, baseline)
            self.assertEqual(db.scalar(select(ReputationTombstone.original_run_id)), "z-root")
            self.assertEqual(db.execute(text("PRAGMA foreign_key_check")).all(), [])

    def test_chain_self_root_exception_does_not_accept_actual_cycles(self):
        """只允许口碑根的单节点自指；普通自指和两种多节点环继续拒绝。"""
        for parent_name, parents in (
            ("related_run_id", {"a": "a"}),
            ("related_run_id", {"a": "b", "b": "a"}),
            ("root_run_id", {"a": "b", "b": "a"}),
        ):
            with self.subTest(parent_name=parent_name, parents=parents):
                rows = [
                    SimpleNamespace(id=key, **{parent_name: value})
                    for key, value in parents.items()
                ]
                with self.assertRaisesRegex(ValueError, "循环"):
                    RetentionService._chains(rows, parent_name)
        # 记录返回顺序不构成根身份依据，子批次先于根也应归为同一组。
        rows = [
            SimpleNamespace(id="a-retry", root_run_id="z-root"),
            SimpleNamespace(id="z-root", root_run_id="z-root"),
        ]
        self.assertEqual(RetentionService._chains(rows, "root_run_id"), [["a-retry", "z-root"]])

    def test_reputation_active_child_or_report_blocks_manual_and_automatic(self):
        self.reputation_run("root")
        self.reputation_run("retry", source="retry", parent="root", status="running")
        with self.assertRaisesRegex(Exception, "关联补跑"):
            self.reputation.delete_official("root")
        self.assertEqual(self.service.preview(self.now)["eligible"], [])
        with self.factory.begin() as db:
            run = db.get(ReputationRun, "retry")
            run.status = "success"
            run.report_status = "generating"
        with self.assertRaisesRegex(Exception, "关联补跑"):
            self.reputation.delete_official("root")
        self.assertEqual(self.service.preview(self.now)["eligible"], [])

    def test_manual_demo_first_does_not_claim_or_change_real_schedule(self):
        """错标scheduled的历史演示先删除，真实日程/批次/原文件必须保持。"""
        self.reputation_run("official")
        self.reputation_run("manual", key="reputation:manual-demo:manual")
        with self.factory.begin() as db:
            db.add(ReputationScheduleEvent(id="event", planned_date=self.old.date().isoformat(),
                   run_type="daily", planned_at=self.old, run_id="manual", status="success", message="original"))
        # canonical身份与事件归属冲突时，须在搬运任何文件/创建删除作业前拒绝。
        with self.assertRaisesRegex(Exception, "其他批次"):
            self.reputation.delete_official("official")
        with self.factory.begin() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(ReputationDeleteJob)), 0)
            db.get(ReputationScheduleEvent, "event").run_id = "official"
        original = (self.settings.reputation_dir / "official/region.png").read_bytes()
        deleted = self.reputation.delete_official("manual")
        self.assertEqual(deleted["status"], "success", deleted)
        with self.factory() as db:
            self.assertIsNone(db.get(ReputationRun, "manual"))
            self.assertIsNotNone(db.get(ReputationRun, "official"))
            event = db.get(ReputationScheduleEvent, "event")
            self.assertEqual((event.run_id, event.status, event.message), ("official", "success", "original"))
            self.assertEqual(db.scalar(select(func.count()).select_from(ReputationTombstone)), 0)
        self.assertEqual((self.settings.reputation_dir / "official/region.png").read_bytes(), original)

    def test_official_first_then_manual_preserves_existing_tombstone_and_event(self):
        """与生产失败次序一致：正式先形成日期墓碑，随后演示只走自身删除审计。"""
        self.reputation_run("official")
        self.reputation_run("manual", key="reputation:manual-demo:manual")
        with self.factory.begin() as db:
            db.add(ReputationScheduleEvent(id="event", planned_date=self.old.date().isoformat(),
                   run_type="daily", planned_at=self.old, run_id="official", status="success", message="original"))
        self.assertEqual(self.reputation.delete_official("official")["status"], "success")
        with self.factory() as db:
            tombstone = db.scalar(select(ReputationTombstone))
            original = (tombstone.id, tombstone.original_run_id, tombstone.idempotency_key,
                        tombstone.result_hash, tombstone.deleted_at)
            event = db.get(ReputationScheduleEvent, "event")
            event_before = (event.run_id, event.status, event.message)
        deleted = self.reputation.delete_official("manual")
        self.assertEqual(deleted["status"], "success", deleted)
        with self.factory() as db:
            tombstone = db.scalar(select(ReputationTombstone))
            self.assertEqual((tombstone.id, tombstone.original_run_id, tombstone.idempotency_key,
                              tombstone.result_hash, tombstone.deleted_at), original)
            event = db.get(ReputationScheduleEvent, "event")
            self.assertEqual((event.run_id, event.status, event.message), event_before)
            self.assertEqual(db.scalar(select(func.count()).select_from(ReputationDeleteJob)), 2)
            self.assertEqual(db.scalar(select(func.count()).select_from(ReputationRun)), 0)
            self.assertEqual(db.execute(text("PRAGMA foreign_key_check")).all(), [])

    def test_null_key_requires_own_event_and_existing_tombstone_is_not_overwritten(self):
        """旧空key必须有事件归属证明；无证明者不占日期，矛盾canonical行预先阻断。"""
        self.reputation_run("legacy", key=None)
        with self.factory.begin() as db:
            db.add(ReputationScheduleEvent(id="event", planned_date=self.old.date().isoformat(),
                   run_type="daily", planned_at=self.old, run_id="legacy", status="success", message="original"))
        self.assertEqual(self.reputation.delete_official("legacy")["status"], "success")
        with self.factory() as db:
            stone = db.scalar(select(ReputationTombstone))
            stone_id, frozen_hash = stone.id, stone.result_hash
            self.assertEqual(stone.idempotency_key, f"reputation:{self.old.date().isoformat()}:daily")
        self.reputation_run("unproven", key=None)
        self.assertEqual(self.reputation.delete_official("unproven")["status"], "success")
        self.reputation_run("conflicting-canonical")
        with self.assertRaisesRegex(Exception, "墓碑已存在"):
            self.reputation.delete_official("conflicting-canonical")
        with self.factory() as db:
            stone = db.scalar(select(ReputationTombstone))
            self.assertEqual((stone.id, stone.result_hash, stone.original_run_id), (stone_id, frozen_hash, "legacy"))
            self.assertEqual(db.scalar(select(func.count()).select_from(ReputationTombstone)), 1)
            self.assertIsNotNone(db.get(ReputationRun, "conflicting-canonical"))
            self.assertEqual(db.scalar(select(func.count()).select_from(ReputationDeleteJob)), 2)
        self.assertTrue((self.settings.reputation_dir / "conflicting-canonical/region.png").is_file())

    def test_reputation_cleanup_failure_and_repeat_retry(self):
        self.reputation_run("root")
        with patch("threadsnap.reputation.shutil.rmtree", side_effect=PermissionError("locked")):
            result = self.reputation.delete_official("root")
        self.assertEqual(result["status"], "storage_cleanup_pending")
        with self.factory() as db:
            self.assertIsNone(db.get(ReputationRun, "root"))
        self.assertEqual(
            self.make_service().process_once(self.now, force=True)["status"], "complete"
        )
        self.assertEqual(self.reputation.retry_delete_cleanup(result["id"])["status"], "success")

    def test_reputation_interrupted_move_resumes_without_new_job(self):
        self.reputation_run("root")
        original = self.settings.reputation_dir / "root/region.png"
        digest = hashlib.sha256(original.read_bytes()).hexdigest()
        quarantine = self.settings.reputation_dir / ".quarantine/job"
        saved = quarantine / "root/region.png"
        saved.parent.mkdir(parents=True)
        original.replace(saved)
        with self.factory.begin() as db:
            db.add(
                ReputationDeleteJob(
                    id="job",
                    root_run_id="root",
                    idempotency_key="delete:root",
                    status="deleting",
                    quarantine_path=str(quarantine.resolve()),
                    manifest=[
                        {
                            "path": str(original.resolve()),
                            "relative_path": "root/region.png",
                            "sha256": digest,
                            "size": saved.stat().st_size,
                        }
                    ],
                )
            )
        result = self.reputation.retry_delete_cleanup("job")
        self.assertEqual(result["status"], "success", result)
        with self.factory() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(ReputationDeleteJob)), 1)
            self.assertIsNone(db.get(ReputationRun, "root"))
        self.assertFalse((self.settings.reputation_dir / "root").exists())

    def test_reputation_delete_failed_reuses_job_and_preserves_files_until_retry(self):
        self.reputation_run("root")
        original_replace = Path.replace

        def fail_move(path, target):
            if ".quarantine" in str(target):
                raise PermissionError("injected move failure")
            return original_replace(path, target)

        with patch.object(Path, "replace", fail_move):
            failed = self.reputation.delete_official("root")
        self.assertEqual(failed["status"], "delete_failed")
        self.assertTrue((self.settings.reputation_dir / "root/region.png").exists())
        fixed = self.reputation.retry_delete_cleanup(failed["id"])
        self.assertEqual(fixed["status"], "success", fixed)
        self.assertEqual(fixed["id"], failed["id"])

    def test_reputation_tampered_quarantine_cannot_remove_data_root(self):
        with self.factory.begin() as db:
            db.add(
                ReputationDeleteJob(
                    id="bad",
                    root_run_id="old",
                    idempotency_key="delete:old",
                    status="storage_cleanup_pending",
                    quarantine_path=str(self.settings.data_dir),
                    manifest=[],
                )
            )
        sentinel = self.settings.data_dir / "keep.bin"
        sentinel.write_bytes(b"keep")
        with self.assertRaisesRegex(ValueError, "隔离区"):
            self.reputation.retry_delete_cleanup("bad")
        self.assertEqual(sentinel.read_bytes(), b"keep")

    def test_recent_ai_result_extends_retention_without_cache_time_dependency(self):
        self.extraction("root")
        with self.factory.begin() as db:
            db.add(
                SentimentAnalysis(
                    post_id="post-root",
                    platform_code="dongchedi",
                    platform_post_id="root",
                    input_hash="a",
                    status="analysis_success",
                    config_revision=1,
                    subject_version=1,
                    model_code="test",
                    created_at=self.old,
                    finished_at=self.now - timedelta(days=2),
                )
            )
        self.assertEqual(self.service.preview(self.now)["eligible"], [])
        self.assertEqual(
            self.service.preview(self.now)["skipped"][0]["last_activity_at"],
            (self.now - timedelta(days=2)).isoformat(),
        )


if __name__ == "__main__":
    unittest.main()
