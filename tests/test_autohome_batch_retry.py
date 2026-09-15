"""真实Worker和隔离SQLite下的汽车之家批次尾轮合同，不访问平台。"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import select

from tests.test_backend import AppCase, sample_record
from threadsnap.collectors import AuthenticationRequired, CollectorFailure
from threadsnap.collectors.autohome import AutohomeCollector, normalize_post_url
from threadsnap.models import Circle, CircleTask, PlatformConfig, PostSnapshot
from threadsnap.schemas import ManualRunCreate
from threadsnap.worker import (
    FROZEN_CANDIDATES_KEY,
    HOMEPAGE_PENDING_KEY,
    HOMEPAGE_RETRY_ROUND_KEY,
    SOURCE_BATCH_RETRY_USED_KEY,
    WorkerService,
)

HOME = "PLATFORM_HOME_REDIRECT"
NETWORK = "PLATFORM_NETWORK_ERROR"
RATE = "PLATFORM_RATE_LIMITED"
AUTH = "PLATFORM_CHALLENGE"
INVALID = "PLATFORM_RESPONSE_INVALID"


def candidate(post_id: int, position: int = 0) -> dict:
    """构造带发现来源、原始论坛与列表字段的固定候选。"""
    return {
        "post_id": str(post_id),
        "url": f"https://club.autohome.com.cn/bbs/thread/abcdef/{post_id}-1.html",
        "source_position": position,
        "order_index": position,
        "bbs_id": 7853,
        "bbs_type": "c",
        "canonical_bbs_id_hint": 999,
        "canonical_bbs_type_hint": "c",
        "reply_count": 17,
        "is_delete": 0,
        "club_delete_flag": 0,
    }


class PlannedCollector(AutohomeCollector):
    """保留生产collect_circle/collect_urls，只以确定性列表/详情代替网络。"""

    def __init__(self, rows: dict[str, list[dict]], plans: dict[str, list[str]]):
        super().__init__(None)
        self.rows = rows
        self.plans = plans
        self.calls: list[tuple[str, dict | None]] = []
        self.list_calls: list[str] = []
        self.extra_source_errors: list[str] = []

    def _list_page(self, source, _page):
        self.list_calls.append(source.url)
        if self.extra_source_errors:
            raise CollectorFailure(self.extra_source_errors.pop(0), "来源暂时失败")
        rows = self.rows[source.external_id]
        return {"items": rows, "total": len(rows)}

    @staticmethod
    def _candidate(_source, item, _source_index):
        return dict(item)

    def fetch_post(self, post_url, *, candidate=None):
        self.calls.append((post_url, candidate))
        outcomes = self.plans.get(post_url, [])
        outcome = outcomes.pop(0) if outcomes else "success"
        if outcome == "auth":
            raise AuthenticationRequired("等待会话", trigger_url=post_url)
        if outcome != "success":
            raise CollectorFailure(outcome, "确定性响应", trigger_url=post_url)
        post_id, normalized = normalize_post_url(post_url)
        value = sample_record(post_id)
        value["url"] = normalized
        value["raw_status"] = {"candidate_context": candidate}
        return value

    def close(self):
        """本夹具不建立HTTP会话，允许在连续Worker轮次共享请求记录。"""


class HomepageBatchRetryTest(AppCase):
    def make_run(self, rows: list[list[dict]], plans=None):
        ids = []
        with self.container.sessions.begin() as db:
            db.get(PlatformConfig, "autohome").enabled = True
            for index in range(len(rows)):
                circle = Circle(
                    platform_code="autohome", external_id=str(7853 + index),
                    name=f"来源{index}",
                    url=f"https://club.autohome.com.cn/bbs/forum-c-{7853 + index}-1.html?sort=post",
                    section="dynamic", list_order="latest_publish", source_kind="configured",
                    validation_status="verified",
                )
                db.add(circle)
                db.flush()
                ids.append(circle.id)
        result = self.container.runs.create_manual(ManualRunCreate(
            platform_code="autohome", circle_ids=ids, quantity=max(map(len, rows)),
            ai_analysis_enabled=False, screenshot_enabled=False,
            idempotency_key="homepage-three-waves-0001",
        ), scope="api")
        collector = PlannedCollector({str(7853+i): values for i, values in enumerate(rows)}, plans or {})
        self.container.worker._collector = lambda *_: collector
        self.container.worker._refresh_after_auth = lambda *_: False
        return result["id"], collector

    def tasks(self, run_id):
        with self.container.sessions() as db:
            return list(db.scalars(select(CircleTask).where(CircleTask.run_id == run_id).order_by(CircleTask.queue_sequence)))

    def due(self, run_id):
        with self.container.sessions.begin() as db:
            for task in db.scalars(select(CircleTask).where(CircleTask.run_id == run_id)):
                task.checkpoint = {**(task.checkpoint or {}), "retry_not_before": datetime.now(timezone.utc).isoformat()}

    def test_three_additional_rounds_preserve_candidates_and_clear_failures(self):
        first, missing = candidate(115000001), candidate(115000002, 1)
        run_id, collector = self.make_run([[first, missing]], {missing["url"]: [HOME] * 3})
        for round_no in range(4):
            self.assertTrue(self.container.worker.process_once())
            task = self.tasks(run_id)[0]
            if round_no < 3:
                self.assertEqual("queued", task.status)
                self.assertEqual(round_no+1, task.checkpoint[HOMEPAGE_RETRY_ROUND_KEY])
                self.assertEqual(0, task.failed_count)
        result = self.container.runs.get_run(run_id)
        self.assertEqual(("success", 2, 0), tuple(result[k] for k in ("status", "completed_count", "failed_count")))
        self.assertEqual(Counter({first["url"]: 1, missing["url"]: 4}), Counter(url for url, _ in collector.calls))
        self.assertEqual(1, len(collector.list_calls))
        self.assertEqual([missing] * 4, [ctx for url, ctx in collector.calls if url == missing["url"]])
        self.assertEqual([], task.checkpoint["failed_urls"])
        self.assertEqual([], task.checkpoint["terminal_failures"])
        with self.container.sessions() as db:
            saved = db.scalar(select(PostSnapshot).where(PostSnapshot.url == missing["url"]))
            self.assertEqual(1, saved.order_index)
            self.assertEqual(missing, saved.raw_status["candidate_context"])
        self.assertFalse(self.container.worker.process_once())

    def test_rounds_are_barriers_and_permanent_errors_are_not_retried(self):
        one, okay = candidate(115000011), candidate(115000012, 1)
        bad, two = candidate(115000013), candidate(115000014, 1)
        run_id, collector = self.make_run([[one, okay], [bad, two]], {
            one["url"]: [HOME] * 4,
            bad["url"]: [INVALID],
            two["url"]: [HOME, HOME],
        })
        for _ in range(4):
            self.assertTrue(self.container.worker.process_once())
        result = self.container.runs.get_run(run_id)
        self.assertEqual(("partial_success", 2, 2), tuple(result[k] for k in ("status", "completed_count", "failed_count")))
        urls = [url for url, _ in collector.calls]
        self.assertEqual([one["url"], okay["url"], bad["url"], two["url"], one["url"], two["url"], one["url"], two["url"], one["url"]], urls)
        self.assertEqual(2, len(collector.list_calls))
        self.assertFalse(self.container.worker.process_once())

    def test_mixed_rate_network_auth_and_restart_keep_round_budget(self):
        one, two = candidate(115000021), candidate(115000022, 1)
        run_id, collector = self.make_run([[one, two]], {
            one["url"]: [HOME, NETWORK, AUTH, HOME, HOME, HOME],
            two["url"]: [RATE],
        })
        self.assertTrue(self.container.worker.process_once())
        task = self.tasks(run_id)[0]
        self.assertEqual(RATE, task.checkpoint["retry_error_code"])
        self.assertEqual(0, task.checkpoint[HOMEPAGE_RETRY_ROUND_KEY])
        self.assertEqual([two["url"]], task.checkpoint["retry_urls"])
        self.assertEqual([one["url"]], [f["url"] for f in task.checkpoint[HOMEPAGE_PENDING_KEY]])
        self.assertFalse(self.container.worker.process_once())
        self.due(run_id)
        self.assertTrue(self.container.worker.process_once())  # 冷却后只恢复限流URL
        self.assertEqual([one["url"], two["url"], two["url"]], [url for url, _ in collector.calls])
        self.assertTrue(self.container.worker.process_once())  # 首页第1轮遇到网络错误
        task = self.tasks(run_id)[0]
        self.assertEqual((1, NETWORK), (task.checkpoint[HOMEPAGE_RETRY_ROUND_KEY], task.checkpoint["retry_error_code"]))
        self.due(run_id)
        self.assertTrue(self.container.worker.process_once())  # 同一轮遇到认证
        task = self.tasks(run_id)[0]
        self.assertEqual("waiting_for_auth", task.status)
        self.assertEqual(1, task.checkpoint[HOMEPAGE_RETRY_ROUND_KEY])
        with self.container.sessions.begin() as db:
            active = db.get(CircleTask, task.id)
            active.status = "running"  # 模拟认证完成后已领取、尚未请求时进程退出
        restarted = WorkerService(self.container.sessions, self.container.session_store)
        restarted._collector = lambda *_: collector
        restarted._refresh_after_auth = lambda *_: False
        restarted.recover_interrupted()
        for round_no in (2, 3, 3):
            self.assertTrue(restarted.process_once())
            self.assertEqual(round_no, self.tasks(run_id)[0].checkpoint[HOMEPAGE_RETRY_ROUND_KEY])
        result = self.container.runs.get_run(run_id)
        self.assertEqual(("partial_success", 1, 1), tuple(result[k] for k in ("status", "completed_count", "failed_count")))
        self.assertEqual(6, sum(url == one["url"] for url, _ in collector.calls))
        self.assertEqual(1, len(collector.list_calls))
        self.assertFalse(restarted.process_once())

    def test_waiting_other_platform_first_wave_blocks_home_retry_and_next_run(self):
        row = candidate(115000031)
        run_id, collector = self.make_run([[row]], {row["url"]: [HOME]})
        self.assertTrue(self.container.worker._process_platform_head("autohome"))
        with self.container.sessions.begin() as db:
            source = db.scalar(select(CircleTask).where(CircleTask.run_id == run_id))
            sibling = CircleTask(
                run_id=run_id, platform_code="dongchedi", circle_url="https://www.dongchedi.com/community/24729",
                external_id="24729", status="waiting_for_auth", target_count=1,
                config_snapshot={"ai_analysis_enabled": False, "screenshot_enabled": False},
                queue_sequence=source.queue_sequence + 1,
            )
            db.add(sibling)
            db.flush()
            sibling_id = sibling.id
        self.assertFalse(self.container.worker._process_platform_head("autohome"))
        self.assertEqual(1, len(collector.calls))
        with self.container.sessions.begin() as db:
            db.get(CircleTask, sibling_id).status = "success"
        self.assertTrue(self.container.worker._process_platform_head("autohome"))
        self.assertEqual(2, len(collector.calls))

    def test_source_retry_budget_survives_network_and_home_retries(self):
        row = candidate(115000041)
        run_id, collector = self.make_run([[row]], {row["url"]: [HOME] * 3})
        collector.extra_source_errors = ["PAGE_EVIDENCE_LIST_RESPONSE_MISSING", NETWORK]
        self.assertTrue(self.container.worker.process_once())
        self.due(run_id)
        self.assertTrue(self.container.worker.process_once())
        self.assertTrue(self.tasks(run_id)[0].checkpoint[SOURCE_BATCH_RETRY_USED_KEY])
        self.due(run_id)
        for _ in range(4):
            self.assertTrue(self.container.worker.process_once())
        self.assertEqual("success", self.container.runs.get_run(run_id)["status"])
        self.assertEqual(4, len(collector.calls))
        self.assertEqual(3, len(collector.list_calls))

    def test_first_wave_auth_keeps_home_failures_and_frozen_remaining_urls(self):
        one, two, three = candidate(115000051), candidate(115000052, 1), candidate(115000053, 2)
        run_id, collector = self.make_run([[one, two, three]], {one["url"]: [HOME], two["url"]: ["auth"]})
        self.assertTrue(self.container.worker.process_once())
        task = self.tasks(run_id)[0]
        self.assertEqual("waiting_for_auth", task.status)
        self.assertEqual(3, len(task.checkpoint[FROZEN_CANDIDATES_KEY]))
        with self.container.sessions.begin() as db:
            db.get(CircleTask, task.id).status = "queued"
        self.assertTrue(self.container.worker.process_once())
        self.assertEqual([one["url"], two["url"], two["url"], three["url"]], [url for url, _ in collector.calls])
        self.assertTrue(self.container.worker.process_once())
        self.assertEqual("success", self.container.runs.get_run(run_id)["status"])
        self.assertEqual(1, len(collector.list_calls))

    def test_restart_after_responses_does_not_repeat_completed_wave(self):
        one, two = candidate(115000081), candidate(115000082, 1)
        run_id, collector = self.make_run([[one, two]], {one["url"]: [HOME] * 3})
        for expected_round in (1, 2, 3):
            with patch.object(self.container.worker, "_apply_result", side_effect=RuntimeError("simulated crash")):
                with self.assertRaises(RuntimeError):
                    self.container.worker.process_once()
            before = len(collector.calls)
            self.container.worker.recover_interrupted()
            self.assertTrue(self.container.worker.process_once())
            self.assertEqual(before, len(collector.calls))
            self.assertEqual(expected_round, self.tasks(run_id)[0].checkpoint[HOMEPAGE_RETRY_ROUND_KEY])
        self.assertTrue(self.container.worker.process_once())
        self.assertEqual("success", self.container.runs.get_run(run_id)["status"])
        self.assertEqual(Counter({one["url"]: 4, two["url"]: 1}), Counter(url for url, _ in collector.calls))
        self.assertEqual(1, len(collector.list_calls))

    def test_source_second_missing_remains_terminal_after_network_interruption(self):
        row = candidate(115000091)
        run_id, collector = self.make_run([[row]])
        collector.extra_source_errors = ["PAGE_EVIDENCE_LIST_RESPONSE_MISSING", NETWORK, "PAGE_EVIDENCE_LIST_RESPONSE_MISSING"]
        for _ in range(3):
            self.due(run_id)
            self.assertTrue(self.container.worker.process_once())
        task = self.tasks(run_id)[0]
        self.assertEqual("failed", task.status)
        self.assertEqual("PAGE_EVIDENCE_LIST_RESPONSE_MISSING", task.error_code)
        self.assertEqual(0, len(collector.calls))
        self.assertFalse(self.container.worker.process_once())

    def test_auto_auth_refresh_does_not_rediscover_or_repeat_home_in_same_wave(self):
        one, two, three = candidate(115000071), candidate(115000072, 1), candidate(115000073, 2)
        run_id, collector = self.make_run([[one, two, three]], {one["url"]: [HOME], two["url"]: ["auth"]})
        self.container.worker._refresh_after_auth = lambda *_: True
        self.assertTrue(self.container.worker.process_once())
        self.assertEqual([one["url"], two["url"], two["url"], three["url"]], [url for url, _ in collector.calls])
        self.assertEqual(1, len(collector.list_calls))
        self.assertEqual(1, self.tasks(run_id)[0].checkpoint[HOMEPAGE_RETRY_ROUND_KEY])
        self.assertTrue(self.container.worker.process_once())
        self.assertEqual("success", self.container.runs.get_run(run_id)["status"])
        self.assertEqual(1, len(collector.list_calls))

    def test_home_classifier_leaves_other_invalid_responses_terminal(self):
        collector = AutohomeCollector(None)
        url = candidate(115000061)["url"]
        for final_url, expected in [
            ("https://club.autohome.com.cn/", HOME),
            ("https://club.autohome.com.cn/?cache=1", HOME),
            (url, INVALID),
            ("https://club.autohome.com.cn.evil.test/", INVALID),
            ("https://club.autohome.com.cn/bbs/", INVALID),
        ]:
            with self.subTest(final_url=final_url):
                collector._get = lambda *_: SimpleNamespace(url=final_url, content=b"<html>empty</html>", status_code=200)
                with self.assertRaises(CollectorFailure) as caught:
                    collector.fetch_post(url)
                self.assertEqual(expected, caught.exception.code)
        collector.close()
