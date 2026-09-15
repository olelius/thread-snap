"""跨批次全局帖子复用契约测试。

这些用例只走正式 Worker.process_once，采集器使用确定性夹具，不访问网络、AI 或截图。
"""
from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from test_backend import AppCase, sample_record

from threadsnap.collectors.registry import get_platform_spec
from threadsnap.models import (
    Circle,
    CircleTask,
    CommentSnapshot,
    ExtractionRun,
    PlatformConfig,
    PostSnapshot,
)
from threadsnap.schemas import ManualRunCreate


class ReuseCollector:
    """按 skip_post_ids 模拟来源候选，记录实际请求过的帖子。"""

    def __init__(self, platform_code: str, candidates: list[tuple[str, str]]) -> None:
        self.platform_code = platform_code
        self.adapter_version = get_platform_spec(platform_code).adapter_version
        self.candidates = candidates
        self.calls: list[tuple[str, int, set[str]]] = []
        self.requested_ids: list[str] = []
        self.reuse_ids: list[str] = []

    def collect_circle(self, url: str, target: int, skip_post_ids=None, on_progress=None, reuse_records=None):
        skipped = set(skip_post_ids or ())
        reuse_records = reuse_records or {}
        self.calls.append((url, target, skipped))
        records = []
        for post_id, post_url in self.candidates:
            if post_id in skipped:
                continue
            if post_id in reuse_records:
                self.reuse_ids.append(post_id)
                record = dict(reuse_records[post_id])
                raw_status = dict(record.get("raw_status") or {})
                raw_status.update({
                    "reuse_source_run_id": record.pop("_reuse_source_run_id", None),
                    "reuse_source_snapshot_id": record.pop("_reuse_source_snapshot_id", None),
                    "reuse_source_fetched_at": record.pop("_reuse_source_fetched_at", None),
                    "reuse_mode": "cross_run_snapshot",
                })
                record["raw_status"] = raw_status
                record["url"] = post_url
                record["platform_post_id"] = post_id
                record["order_index"] = len(records)
            else:
                record = sample_record(post_id)
                record["url"] = post_url
                record["platform_post_id"] = post_id
                record["section"] = "forum"
                self.requested_ids.append(post_id)
            records.append(record)
            if on_progress:
                on_progress(record, None)
            if len(records) >= target:
                break
        return {"records": records, "failures": [], "stop_reason": "夹具完成。"}

    def close(self) -> None:
        pass


class GlobalPostReuseTests(AppCase):
    def _circle(self, platform_code: str, external_id: str) -> Circle:
        with self.container.sessions.begin() as db:
            platform = db.get(PlatformConfig, platform_code)
            assert platform is not None
            platform.enabled = True
            platform.adapter_status = "available"
            circle = Circle(
                platform_code=platform_code,
                external_id=external_id,
                name=f"来源-{platform_code}-{external_id}",
                url=f"https://{platform_code}.example.test/circle/{external_id}",
                section="forum",
                list_order="latest_reply",
                source_kind="configured",
                validation_status="verified",
            )
            db.add(circle)
            db.flush()
            return deepcopy(circle)

    def _old_run_with_posts(
        self,
        circle: Circle,
        posts: list[dict],
    ) -> tuple[str, str]:
        with self.container.sessions.begin() as db:
            run = ExtractionRun(
                number=f"old-{circle.platform_code}-{circle.external_id}",
                trigger_type="scheduled",
                status="success",
                planned_count=len(posts),
                completed_count=len(posts),
                idempotency_scope="old",
                idempotency_key=f"old-{circle.platform_code}-{circle.external_id}",
                request_hash="a" * 64,
            )
            db.add(run)
            db.flush()
            task = CircleTask(
                run_id=run.id,
                circle_id=circle.id,
                platform_code=circle.platform_code,
                external_id=circle.external_id,
                circle_name=circle.name,
                circle_url=circle.url,
                section=circle.section,
                list_order=circle.list_order,
                status="success",
                queue_sequence=1,
                target_count=len(posts),
                completed_count=len(posts),
                config_snapshot={"ai_analysis_enabled": False, "screenshot_enabled": False},
                checkpoint={},
            )
            db.add(task)
            db.flush()
            for index, value in enumerate(posts):
                post = PostSnapshot(
                    run_id=run.id,
                    circle_task_id=task.id,
                    platform_post_id=value["platform_post_id"],
                    url=value["url"],
                    title=value.get("title", "历史标题"),
                    author=value.get("author", "历史作者"),
                    content=value.get("content", "历史正文"),
                    image_urls=value.get("image_urls", ["https://img.test/history.jpg"]),
                    reply_count=value.get("reply_count", 7),
                    like_count=value.get("like_count", 9),
                    section=value.get("section", "forum"),
                    visibility=value.get("visibility", "visible"),
                    raw_status=(
                        dict(value.get("raw_status") or {"source": "history"})
                        if value.get("omit_adapter_version")
                        else {
                            "adapter_version": get_platform_spec(circle.platform_code).adapter_version,
                            **(value.get("raw_status") or {"source": "history"}),
                        }
                    ),
                    order_index=index,
                )
                db.add(post)
                db.flush()
                for comment_index, comment in enumerate(value.get("comments", [])):
                    db.add(CommentSnapshot(
                        post_id=post.id,
                        platform_comment_id=comment.get("platform_comment_id", f"c-{post.platform_post_id}"),
                        author=comment.get("author", "评论作者"),
                        content=comment.get("content", "历史评论"),
                        like_count=comment.get("like_count", 1),
                        order_index=comment_index,
                    ))
            return run.id, task.id

    def _new_run(self, circle: Circle, quantity: int, key: str) -> str:
        result = self.container.runs.create_manual(
            # 直接传入圈子，避免测试绕过 RunService 的输入契约。
            ManualRunCreate(
                platform_code=circle.platform_code,
                circle_ids=[circle.id],
                quantity=quantity,
                ai_analysis_enabled=False,
                screenshot_enabled=False,
            ),
            scope="api",
            header_key=key,
        )
        return result["id"]

    def _run(self, run_id: str, collector: ReuseCollector) -> None:
        self.container.worker._collector = lambda platform, *_: collector
        self.container.worker.screenshot_service = None
        self.container.worker.sentiment_service = SimpleNamespace(enqueue_for_post=Mock())
        self.assertTrue(self.container.worker.process_once())
        self.assertFalse(self.container.worker.process_once())

    def _task_posts(self, run_id: str) -> list[PostSnapshot]:
        with self.container.sessions() as db:
            task = db.scalar(select(CircleTask).where(CircleTask.run_id == run_id))
            assert task is not None
            return list(db.scalars(select(PostSnapshot).options(selectinload(PostSnapshot.comments)).where(PostSnapshot.circle_task_id == task.id).order_by(PostSnapshot.order_index)))

    def test_same_platform_id_is_reused_as_independent_snapshot_with_provenance(self) -> None:
        circle = self._circle("dongchedi", "reuse-source")
        old_url = "https://dongchedi.example.test/post/shared"
        new_url = "https://dongchedi.example.test/post/new"
        self._old_run_with_posts(circle, [{
            "platform_post_id": "shared-1", "url": old_url,
            "title": "保留历史标题", "content": "保留历史正文",
            "comments": [{"platform_comment_id": "comment-1", "content": "保留评论"}],
        }])
        run_id = self._new_run(circle, 2, "global-reuse-same-platform")
        collector = ReuseCollector("dongchedi", [("shared-1", old_url), ("new-1", new_url)])
        self._run(run_id, collector)

        # 旧 ID 必须进入全局 skip，实际采集只请求新帖子。
        self.assertEqual(["new-1"], collector.requested_ids)
        self.assertEqual(["shared-1"], collector.reuse_ids)
        posts = self._task_posts(run_id)
        self.assertEqual(["shared-1", "new-1"], [post.platform_post_id for post in posts])
        reused = posts[0]
        self.assertEqual(("保留历史标题", "保留历史正文"), (reused.title, reused.content))
        self.assertEqual("保留评论", reused.comments[0].content)
        self.assertEqual(0, reused.order_index)
        self.assertEqual(run_id, reused.run_id)
        self.assertIsNotNone(reused.raw_status)
        raw_status = reused.raw_status or {}
        self.assertEqual("cross_run_snapshot", raw_status["reuse_mode"])
        self.assertNotEqual(run_id, raw_status["reuse_source_run_id"])
        self.assertIsNotNone(raw_status["reuse_source_snapshot_id"])
        self.assertIsNotNone(raw_status["reuse_source_fetched_at"])

    def test_same_id_on_different_platform_is_not_reused(self) -> None:
        old_circle = self._circle("dongchedi", "same-id-old")
        self._old_run_with_posts(old_circle, [{"platform_post_id": "same-1", "url": "https://dongchedi.example.test/post/same"}])
        new_circle = self._circle("autohome", "same-id-new")
        run_id = self._new_run(new_circle, 1, "global-reuse-cross-platform")
        collector = ReuseCollector("autohome", [("same-1", "https://autohome.example.test/post/same")])
        self._run(run_id, collector)
        self.assertEqual(["same-1"], collector.requested_ids)
        post = self._task_posts(run_id)[0]
        self.assertNotIn("reuse_mode", post.raw_status or {})

    def test_incomplete_history_is_not_reused(self) -> None:
        circle = self._circle("dongchedi", "incomplete-history")
        candidates = [
            ("empty-content", "https://dongchedi.example.test/post/empty"),
            ("unknown-visible", "https://dongchedi.example.test/post/unknown"),
            ("deleted-post", "https://dongchedi.example.test/post/deleted"),
        ]
        self._old_run_with_posts(circle, [
            {"platform_post_id": "empty-content", "url": candidates[0][1], "title": "只有标题", "content": None, "image_urls": [], "video_urls": []},
            {"platform_post_id": "unknown-visible", "url": candidates[1][1], "visibility": "unknown"},
            {"platform_post_id": "deleted-post", "url": candidates[2][1], "raw_status": {"content_state": "deleted"}},
        ])
        run_id = self._new_run(circle, 3, "global-reuse-incomplete-history")
        collector = ReuseCollector("dongchedi", candidates)
        self._run(run_id, collector)
        self.assertEqual({"empty-content", "unknown-visible", "deleted-post"}, set(collector.requested_ids))
        self.assertTrue(all("reuse_mode" not in (post.raw_status or {}) for post in self._task_posts(run_id)))

    def test_complete_legacy_snapshot_without_adapter_version_is_reused(self) -> None:
        circle = self._circle("dongchedi", "legacy-history")
        url = "https://dongchedi.example.test/post/legacy"
        self._old_run_with_posts(circle, [{
            "platform_post_id": "legacy-1", "url": url,
            "title": "旧批次标题", "content": "旧批次正文",
            "omit_adapter_version": True,
        }])
        run_id = self._new_run(circle, 1, "global-reuse-legacy")
        collector = ReuseCollector("dongchedi", [("legacy-1", url)])
        self._run(run_id, collector)
        self.assertEqual([], collector.requested_ids)
        self.assertEqual("cross_run_snapshot", (self._task_posts(run_id)[0].raw_status or {})["reuse_mode"])
