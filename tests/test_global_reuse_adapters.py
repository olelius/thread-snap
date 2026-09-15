"""复用必须在三个生产适配器的详情边界生效，不替换 collect_circle/collect_urls。"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from unittest import TestCase
from unittest.mock import Mock

from sqlalchemy import select
from test_backend import AppCase, sample_record

from threadsnap.collectors.autohome import AutohomeCollector
from threadsnap.collectors.dongchedi import DongchediCollector
from threadsnap.collectors.yiche import YicheCollector
from threadsnap.models import CircleTask, ExtractionRun, PlatformConfig, PostSnapshot
from threadsnap.schemas import ManualRunCreate


def post_url(platform: str, post_id: str) -> str:
    """使用平台已支持的 URL 形态，不由桩替换规范化入口。"""
    return {
        "dongchedi": f"https://www.dongchedi.com/ugc/article/{post_id}",
        "autohome": f"https://club.autohome.com.cn/bbs/thread/abcdef/{post_id}-1.html",
        "yiche": f"https://baa.yiche.com/sample/thread-{post_id}.html",
    }[platform]


def historical_record(platform: str, post_id: str = "810001") -> dict:
    """提供 Worker 索引的真实记录合同，来源标识和抓取时刻可精确断言。"""
    record = sample_record(post_id)
    record.update(
        url=post_url(platform, post_id),
        order_index=77,
        _reuse_source_run_id="historical-run",
        _reuse_source_snapshot_id="historical-snapshot",
        _reuse_source_fetched_at="2026-09-01T01:02:03+00:00",
    )
    return record


class GlobalReuseAdapterTests(TestCase):
    """列表、身份探针及详情请求由有限桩代替，候选循环与复用逻辑为生产代码。"""

    def _collector(self, platform: str):
        collector = {
            "dongchedi": DongchediCollector,
            "autohome": AutohomeCollector,
            "yiche": YicheCollector,
        }[platform](None)
        self.addCleanup(collector.close)
        if platform == "yiche":
            collector._ensure_account_identity = Mock(return_value=None)
        return collector

    def _circle_contract(self, platform: str) -> None:
        collector = self._collector(platform)
        rows = [
            {"post_id": post_id, "url": post_url(platform, post_id), "order_index": position}
            for post_id, position in (("810000", 0), ("810001", 5), ("810002", 9))
        ]
        if platform == "dongchedi":
            source_url = "https://www.dongchedi.com/community/24729"
            collector._fetch_circle_page = Mock(return_value={
                "rows": deepcopy(rows), "total_count": 3, "page_count": 1,
            })
        elif platform == "autohome":
            source_url = "https://club.autohome.com.cn/bbs/forum-c-7853-1.html"
            collector._list_page = Mock(return_value={"items": deepcopy(rows), "total": 3})
            collector._candidate = lambda _source, item, _index: dict(item)
        else:
            source_url = "https://baa.yiche.com/sample/"
            collector._list_page = Mock(return_value={"list": deepcopy(rows), "total": 3})
            collector._candidate = lambda _source, item, _index: dict(item)
        fresh = sample_record("810002")
        fresh["url"] = rows[2]["url"]
        fetch = Mock(return_value=fresh)
        if platform == "yiche":
            collector._fetch_post = fetch
        else:
            collector.fetch_post = fetch
        cached = historical_record(platform)
        before = deepcopy(cached)
        progress = Mock()
        result = collector.collect_circle(
            source_url, 2, skip_post_ids={"810000"},
            on_progress=progress, reuse_records={"810001": cached},
        )
        self.assertEqual([], result["failures"])
        self.assertEqual(["810001", "810002"], [r["platform_post_id"] for r in result["records"]])
        self.assertEqual([5, 9], [r["order_index"] for r in result["records"]])
        self.assertEqual(rows[1]["url"], result["records"][0]["url"])
        self.assertEqual("cross_run_snapshot", result["records"][0]["raw_status"]["reuse_mode"])
        self.assertEqual(2, progress.call_count)
        fetch.assert_called_once()
        self.assertEqual(rows[2]["url"], fetch.call_args.args[0])
        self.assertEqual(before, cached, "复用输入应保持不可变")

    def test_dongchedi_circle_uses_real_candidate_loop(self) -> None:
        self._circle_contract("dongchedi")

    def test_autohome_circle_keeps_candidate_record_error_tuple(self) -> None:
        self._circle_contract("autohome")

    def test_yiche_circle_uses_real_candidate_loop(self) -> None:
        self._circle_contract("yiche")

    def test_three_real_url_collectors_skip_only_cached_details(self) -> None:
        """命中和未命中并列，实际 fetch 只接到未命中 URL。"""
        for platform in ("dongchedi", "autohome", "yiche"):
            with self.subTest(platform=platform):
                collector = self._collector(platform)
                cached = historical_record(platform)
                fresh = sample_record("810002")
                fresh["url"] = post_url(platform, "810002")
                fetch = Mock(return_value=fresh)
                if platform == "yiche":
                    collector._fetch_post = fetch
                else:
                    collector.fetch_post = fetch
                urls = [post_url(platform, "810001"), post_url(platform, "810002")]
                result = collector.collect_urls(urls, reuse_records={"810001": cached})
                self.assertEqual([], result["failures"])
                self.assertEqual([0, 1], [r["order_index"] for r in result["records"]])
                fetch.assert_called_once()
                self.assertEqual(urls[1], fetch.call_args.args[0])
                self.assertEqual(
                    "2026-09-01T01:02:03+00:00",
                    result["records"][0]["raw_status"]["reuse_source_fetched_at"],
                )


class GlobalReuseLegacyLifecycleTests(AppCase):
    def test_legacy_post_and_repeated_reuse_keep_original_capture_time(self) -> None:
        """旧汽车之家 response_class=post 无版本；两次新批次均走真实 URL 采集器。"""
        fetched_at = datetime(2026, 9, 1, 1, 2, 3, tzinfo=timezone.utc)
        with self.container.sessions.begin() as db:
            db.get(PlatformConfig, "autohome").enabled = True
            original_run = ExtractionRun(
                number="legacy-global-reuse", trigger_type="manual", status="success",
                planned_count=1, completed_count=1,
                idempotency_scope="test", idempotency_key="legacy-global-reuse",
                request_hash="a" * 64,
            )
            db.add(original_run)
            db.flush()
            original_task = CircleTask(
                run_id=original_run.id, platform_code="autohome",
                external_id="known-url-list", circle_url="", status="success",
                target_count=1, completed_count=1, queue_sequence=1,
                config_snapshot={"ai_analysis_enabled": False, "screenshot_enabled": False},
            )
            db.add(original_task)
            db.flush()
            original_post = PostSnapshot(
                run_id=original_run.id, circle_task_id=original_task.id,
                platform_post_id="810001", url=post_url("autohome", "810001"),
                title="历史完整标题", content="历史完整正文", visibility="visible",
                raw_status={"response_class": "post", "topic_id": "810001"},
                order_index=0, created_at=fetched_at,
            )
            db.add(original_post)
            db.flush()
            original_id = original_post.id
        collector = AutohomeCollector(None)
        self.addCleanup(collector.close)
        collector.fetch_post = Mock(side_effect=AssertionError("缓存命中不应访问详情"))
        self.container.worker._collector = lambda *_: collector
        self.container.worker.sentiment_service = None
        self.container.worker.screenshot_service = None
        seen_snapshots = {original_id}
        for index in range(2):
            result = self.container.runs.create_manual(
                ManualRunCreate(
                    platform_code="autohome", quantity=1,
                    known_post_urls=[post_url("autohome", "810001")],
                    ai_analysis_enabled=False, screenshot_enabled=False,
                ), scope="test", header_key=f"legacy-repeat-{index}",
            )
            self.assertTrue(self.container.worker.process_once())
            with self.container.sessions() as db:
                run = db.get(ExtractionRun, result["id"])
                self.assertEqual(("success", 1, 0), (run.status, run.completed_count, run.failed_count))
                post = db.scalar(select(PostSnapshot).where(PostSnapshot.run_id == result["id"]))
                self.assertIsNotNone(post)
                self.assertNotIn(post.id, seen_snapshots)
                seen_snapshots.add(post.id)
                self.assertEqual(fetched_at.isoformat(), post.raw_status["reuse_source_fetched_at"])
                self.assertEqual("cross_run_snapshot", post.raw_status["reuse_mode"])
                original = db.get(PostSnapshot, original_id)
                self.assertEqual({"response_class": "post", "topic_id": "810001"}, original.raw_status)
        collector.fetch_post.assert_not_called()
