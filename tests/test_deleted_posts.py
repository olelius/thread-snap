"""删除状态只走成功快照，普通空正文仍走既有错误；不访问平台或模型。"""

from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import select
from test_autohome_collector import FakeResponse, collector_with_like
from test_backend import AppCase

from threadsnap.collectors import CollectorFailure
from threadsnap.collectors.autohome import AutohomeCollector
from threadsnap.models import (
    CircleTask,
    ExtractionRun,
    PlatformConfig,
    PostSnapshot,
    SentimentAnalysis,
)

URL = "https://club.autohome.com.cn/bbs/thread/9c9f0d9e367dad6d/116097983-1.html"


def deleted_html(flag: int = 3, post_id: int = 116097983) -> bytes:
    """使用已保存诊断中的身份/状态及删除提示构造最小页面。"""
    return f"""<html><head><meta charset="utf-8"></head><body><script>
    window['__BBSINFO__'] = {{"bbsId":8232,"bbs":"c"}}
    window['__TOPICINFO__'] = {{topicId: {post_id}, topicTitle: '这个价格怎么样啊', topicDelete: {flag}}};
    </script><div>主楼已被删除</div></body></html>""".encode()


class DeletedPostTests(AppCase):
    def test_deleted_url_worker_succeeds_without_any_ai_or_secondary_request(self) -> None:
        with self.container.sessions.begin() as db:
            db.get(PlatformConfig, "autohome").enabled = True
            run = ExtractionRun(
                number="20260911-160000-001",
                input_mode="url_list",
                trigger_type="manual",
                status="queued",
                idempotency_scope="test",
                idempotency_key="deleted-post",
                request_hash="a" * 64,
                planned_count=1,
            )
            db.add(run)
            db.flush()
            task = CircleTask(
                run_id=run.id,
                platform_code="autohome",
                external_id="known-url-list",
                circle_name="导入帖子链接",
                circle_url="",
                list_order="latest_reply",
                status="queued",
                queue_sequence=1,
                source_position=0,
                target_count=1,
                config_snapshot={
                    "known_post_urls": [URL],
                    "internal_concurrency": 1,
                    "ai_analysis_enabled": True,
                    "ai_account_id": 9999,
                    "screenshot_enabled": False,
                },
            )
            db.add(task)
            db.flush()
            run_id = run.id
        response = SimpleNamespace(content=deleted_html(), url=URL, status_code=200)
        with (
            patch.object(AutohomeCollector, "_get", return_value=response) as get,
            patch.object(AutohomeCollector, "_topic_like_count") as likes,
            patch.object(AutohomeCollector, "_resolve_video_media") as media,
            patch.object(self.container.sentiment, "require_account") as account,
        ):
            self.assertTrue(self.container.worker.process_once())
            self.assertEqual(1, get.call_count)
            likes.assert_not_called()
            media.assert_not_called()
            account.assert_not_called()
        run = self.client.get(f"/api/v1/runs/{run_id}").json()
        self.assertEqual(
            ("success", 1, 0), (run["status"], run["completed_count"], run["failed_count"])
        )
        post = self.client.get(f"/api/v1/runs/{run_id}/posts").json()["items"][0]
        self.assertTrue(post["is_deleted"])
        self.assertEqual("hidden", post["visibility"])
        self.assertEqual("analysis_disabled", post["analysis_status"])
        self.assertIsNone(post["sentiment_result"])
        self.assertEqual(3, post["raw_status"]["topic_delete"])
        self.assertEqual("主楼已被删除", post["raw_status"]["page_message"])
        detail = self.client.get(f"/api/v1/runs/{run_id}/posts/{post['id']}").json()
        self.assertFalse(detail["sentiment"]["can_manual_correct"])
        manual = self.client.post(
            f"/api/v1/runs/{run_id}/posts/{post['id']}/sentiment/manual-revisions",
            json={"action": "set_result", "result": "non_negative"},
        )
        self.assertEqual(409, manual.status_code)
        with self.container.sessions() as db:
            self.assertIsNone(db.scalar(select(SentimentAnalysis)))
            self.assertEqual(1, len(list(db.scalars(select(PostSnapshot)))))

    def test_empty_hidden_or_quoted_deletion_message_is_not_deletion(self) -> None:
        for flag in (0, 1):
            with self.subTest(flag=flag):
                collector = collector_with_like()
                collector._get = lambda url, **_: FakeResponse(deleted_html(flag), url)
                with self.assertRaises(CollectorFailure) as caught:
                    collector.fetch_post(URL)
                self.assertEqual("POST_CONTENT_MISSING", caught.exception.code)
        self.assertFalse(
            PostSnapshot(visibility="hidden", raw_status={"topic_delete": 1}).is_deleted
        )

    def test_deleted_status_does_not_bypass_post_identity(self) -> None:
        collector = collector_with_like()
        collector._get = lambda url, **_: FakeResponse(deleted_html(post_id=123), url)
        with self.assertRaises(CollectorFailure) as caught:
            collector.fetch_post(URL)
        self.assertEqual("POST_ID_MISMATCH", caught.exception.code)
