"""普通批次列表的窄列批量查询、历史语义和连接归还定向验证。"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import patch

from sqlalchemy import event, inspect, select, text
from test_backend import AppCase

from threadsnap.models import CircleTask, ExtractionRun, ScreenshotArtifactGroup
from threadsnap.services import run_dict


class RunsListQueryTests(AppCase):
    """复用隔离应用工厂；不启动 Worker，也不访问平台或 AI。"""

    def setUp(self) -> None:
        super().setUp()
        self.engine = self.container.sessions.kw["bind"]
        self.serial = 0
        self.base_time = datetime(2026, 9, 21, tzinfo=timezone.utc)

    def seed_run(
        self, *, tasks: list[dict[str, Any]] | None = None, **overrides: Any
    ) -> str:
        """写入有确定顺序的批次；任务配置按调用方覆盖，以保留真实 ORM 默认值。"""

        self.serial += 1
        values = {
            "number": f"query-{self.serial:03d}",
            "trigger_type": "manual",
            "status": "success",
            "idempotency_scope": "test",
            "idempotency_key": f"query-{self.serial}",
            "request_hash": "a" * 64,
            "created_at": self.base_time + timedelta(seconds=self.serial),
            "config_snapshot": {"rules": [{"id": "frozen-rule", "name": "规则", "version": 2}]},
        }
        values.update(overrides)
        with self.container.sessions.begin() as db:
            run = ExtractionRun(**values)
            db.add(run)
            db.flush()
            for index, task_overrides in enumerate([{}] if tasks is None else tasks):
                task_values = {
                    "run_id": run.id,
                    "platform_code": "dongchedi",
                    "external_id": f"source-{self.serial}-{index}",
                    "circle_name": f"圈子-{index}",
                    "circle_url": "https://example.test/circle",
                    "queue_sequence": self.serial * 10 + index,
                    "target_count": 2,
                    "status": "success",
                    "config_snapshot": {},
                }
                task_values.update(task_overrides)
                db.add(CircleTask(**task_values))
            return run.id

    def seed_groups(self, root_id: str, statuses: list[str]) -> None:
        """每个状态写一个来源组，计数独立于状态并可精确求和。"""

        with self.container.sessions.begin() as db:
            for index, status in enumerate(statuses):
                db.add(ScreenshotArtifactGroup(
                    chain_root_run_id=root_id,
                    platform_code="dongchedi",
                    external_id=f"group-{index}",
                    section="dynamic",
                    list_order="latest_reply",
                    status=status,
                    item_count=index + 2,
                    negative_count=index,
                ))

    @contextmanager
    def capture_queries(self) -> Iterator[list[str]]:
        """只捕获目标调用实际发出的 SQL，退出时清理监听器。"""

        statements: list[str] = []

        def record(_conn, _cursor, statement, _parameters, _context, _many) -> None:
            statements.append(statement)

        event.listen(self.engine, "before_cursor_execute", record)
        try:
            yield statements
        finally:
            event.remove(self.engine, "before_cursor_execute", record)

    def assert_matches_detail(self, items: list[dict[str, Any]]) -> None:
        """逐字段对照仍使用原任务、关联链与截图查询路径的详情摘要。"""

        with self.container.sessions() as db:
            for item in items:
                run = db.get(ExtractionRun, item["id"])
                self.assertEqual(run_dict(db, run), item)

    def test_options_empty_tasks_and_all_screenshot_priorities_match_detail(self) -> None:
        expected: dict[str, str] = {}
        priorities = [
            "failed", "evidence_running", "rendering", "waiting_for_sentiment",
            "evidence_pending", "ready", "empty",
        ]
        for index, status in enumerate(priorities):
            run_id = self.seed_run()
            self.seed_groups(run_id, priorities[index:])
            expected[run_id] = "ready" if status == "empty" else status
        root = next(iter(expected))
        child = self.seed_run(related_run_id=root)
        expected[child] = "failed"
        expected[self.seed_run(related_run_id=child)] = "failed"
        expected[self.seed_run(related_run_id=root, tasks=[])] = "failed"
        expected[self.seed_run(tasks=[])] = "not_collected"
        expected[self.seed_run(tasks=[], status="running")] = "evidence_pending"
        expected[self.seed_run(status="failed")] = "not_collected"
        expected[self.seed_run(status="queued")] = "evidence_pending"
        empty_with_group = self.seed_run(tasks=[])
        self.seed_groups(empty_with_group, ["ready"])
        expected[empty_with_group] = "ready"
        disabled = self.seed_run(
            related_run_id=root, tasks=[{"config_snapshot": {"screenshot_enabled": False}}]
        )
        expected[disabled] = "not_applicable"
        mixed = self.seed_run(
            related_run_id=root,
            tasks=[{"config_snapshot": {"screenshot_enabled": False}}, {}],
        )
        expected[mixed] = "failed"
        url_run = self.seed_run(related_run_id=root, input_mode="url_list")
        expected[url_run] = "not_applicable"
        actual = self.container.runs.list_runs()
        self.assertEqual(len(expected), actual["total"])
        self.assert_matches_detail(actual["items"])
        self.assertEqual(expected, {
            item["id"]: item["screenshot_summary"]["status"] for item in actual["items"]
        })
        root_summary = next(item for item in actual["items"] if item["id"] == root)[
            "screenshot_summary"
        ]
        self.assertEqual({
            "status": "failed", "group_count": 7, "ready_count": 2,
            "item_count": 35, "negative_count": 21,
        }, root_summary)

    def test_fifty_rows_use_constant_queries_and_never_load_checkpoints(self) -> None:
        circle = self.save_verified_circle(name="当前来源")
        for _ in range(50):
            run_id = self.seed_run(status="queued", tasks=[{
                "circle_id": circle.id,
                "status": "queued",
                "checkpoint": {"unused": "重" * 32_768},
            }, {"status": "queued", "checkpoint": {"unused": "文" * 32_768}}])
            self.seed_groups(run_id, ["ready"])

        # 无效 JSON 是更强的防退化断言：只要读到 checkpoint，ORM 解码即报错。
        with self.engine.begin() as connection:
            connection.execute(text("UPDATE circle_tasks SET checkpoint = 'not-json'"))
        loaded_columns: list[set[str]] = []

        def record_load(task, _context) -> None:
            loaded_columns.append(set(inspect(task).dict))

        event.listen(CircleTask, "load", record_load)
        try:
            with patch("threadsnap.services.screenshot_summary", side_effect=AssertionError), \
                    patch("threadsnap.services.related_run_ids", side_effect=AssertionError):
                with self.capture_queries() as one:
                    self.container.runs.list_runs(limit=1)
                with self.capture_queries() as fifty:
                    result = self.container.runs.list_runs(limit=50)
        finally:
            event.remove(CircleTask, "load", record_load)
        self.assertEqual(50, len(result["items"]))
        self.assertEqual(6, len(one))
        self.assertEqual(6, len(fifty))
        self.assertTrue(loaded_columns)
        self.assertTrue(all("checkpoint" not in columns for columns in loaded_columns))
        sql = "\n".join(fifty).lower()
        for forbidden in ("checkpoint", "post_snapshots", "comment_snapshots", "request_hash"):
            self.assertNotIn(forbidden, sql)
        task_queries = [statement for statement in fifty if "FROM circle_tasks" in statement]
        self.assertEqual(2, len(task_queries))
        self.assertNotIn("config_snapshot", task_queries[1])

    def test_off_page_roots_are_loaded_per_depth_not_per_row(self) -> None:
        leaves = []
        for index in range(50):
            root = self.seed_run(tasks=[])
            parent = self.seed_run(related_run_id=root, tasks=[])
            leaf = self.seed_run(number=f"leaf-{index:03d}", related_run_id=parent)
            self.seed_groups(root, ["ready", "empty"])
            leaves.append(leaf)
        with self.capture_queries() as one:
            self.container.runs.list_runs(number="leaf-", limit=1)
        with self.capture_queries() as fifty:
            result = self.container.runs.list_runs(number="leaf-", limit=50)
        self.assertEqual(set(leaves), {item["id"] for item in result["items"]})
        self.assertEqual(7, len(one))
        self.assertEqual(7, len(fifty))
        parent_queries = [statement for statement in fifty if statement.startswith(
            "SELECT extraction_runs.id, extraction_runs.related_run_id"
        )]
        self.assertEqual(2, len(parent_queries))
        self.assertTrue(all("config_snapshot" not in statement for statement in parent_queries))
        self.assertNotIn("WHERE extraction_runs.related_run_id =", "\n".join(fifty))
        self.assert_matches_detail(result["items"])
        self.assertTrue(all(item["screenshot_summary"] == {
            "status": "ready", "group_count": 2, "ready_count": 2,
            "item_count": 5, "negative_count": 1,
        } for item in result["items"]))

    def test_filter_order_pagination_and_empty_pages_remain_unchanged(self) -> None:
        manual = self.seed_run(number="MATCH-manual", status="running")
        scheduled = self.seed_run(number="MATCH-scheduled", trigger_type="scheduled", tasks=[{
            "list_order": "latest_publish",
        }])
        recurring = self.seed_run(trigger_type="recurring", status="failed")
        url_run = self.seed_run(input_mode="url_list", tasks=[{"circle_url": ""}])
        tie_time = self.base_time + timedelta(seconds=5)
        first_tie = self.seed_run(created_at=tie_time, tasks=[])
        second_tie = self.seed_run(created_at=tie_time, tasks=[])
        ordered = sorted([first_tie, second_tie], reverse=True) + [url_run, recurring, scheduled, manual]
        cases = [
            ({}, ordered),
            ({"number": " match- "}, [scheduled, manual]),
            ({"statuses": ["failed", "running"]}, [recurring, manual]),
            ({"trigger_type": "scheduled"}, [scheduled]),
            ({"trigger_types": ["manual", "scheduled", "manual"]},
             [item for item in ordered if item != recurring]),
            ({"trigger_type": "manual", "trigger_types": ["recurring"]}, []),
            ({"list_order": "latest_reply"}, [recurring, manual]),
            ({"list_order": "latest_publish"}, [scheduled]),
            ({"created_from": self.base_time + timedelta(seconds=2),
              "created_to": self.base_time + timedelta(seconds=3)}, [recurring, scheduled]),
            ({"number": "MATCH", "statuses": ["success"],
              "trigger_types": ["manual", "scheduled"], "list_order": "latest_publish"},
             [scheduled]),
        ]
        for filters, expected in cases:
            for offset, limit in [(0, 50), (1, 2), (99, 2)]:
                with self.subTest(filters=filters, offset=offset):
                    result = self.container.runs.list_runs(offset, limit, **filters)
                    self.assertEqual(len(expected), result["total"])
                    self.assertEqual(expected[offset:offset + limit], [
                        item["id"] for item in result["items"]
                    ])
                    self.assertEqual((offset, limit), (result["offset"], result["limit"]))

    def test_queue_position_current_names_and_snapshot_fallback_match_detail(self) -> None:
        circle = self.save_verified_circle(name="当前用户名称")
        for platform, sequence in [("autohome", 10), ("autohome", 20), ("dongchedi", 30)]:
            self.seed_run(tasks=[{
                "platform_code": platform, "status": "queued", "queue_sequence": sequence,
            }])
        run_id = self.seed_run(tasks=[
            {"platform_code": "autohome", "status": "running", "queue_sequence": 100,
             "circle_id": circle.id, "config_snapshot": {"source_name": "旧名称"}},
            {"status": "queued", "queue_sequence": 150,
             "config_snapshot": {"vehicle_name": "快照车型"}},
            {"platform_code": "autohome", "status": "queued", "queue_sequence": 160,
             "circle_name": "回退圈子", "list_order": "latest_publish"},
            {"status": "waiting_for_auth", "queue_sequence": 170,
             "config_snapshot": {"source_name": "第四来源"}},
        ])
        result = self.container.runs.list_runs()
        self.assert_matches_detail(result["items"])
        item = next(item for item in result["items"] if item["id"] == run_id)
        self.assertEqual(3, item["queue_position"])
        self.assertEqual(["当前用户名称", "快照车型", "回退圈子 · 最新发布"], item["source_names"])
        self.assertEqual(4, item["circle_count"])
        self.assertEqual(["dongchedi"], item["waiting_platform_codes"])

    def test_session_returns_connection_after_success_empty_and_failures(self) -> None:
        run_id = self.seed_run()
        self.seed_groups(run_id, ["ready"])
        checked_out: list[int] = []
        checked_in: list[int] = []

        def checkout(connection, _record, _proxy) -> None:
            checked_out.append(id(connection))

        def checkin(connection, _record) -> None:
            checked_in.append(id(connection))

        def fail_groups(_conn, _cursor, statement, _parameters, _context, _many) -> None:
            if "FROM screenshot_artifact_groups" in statement:
                raise RuntimeError("查询失败夹具")

        event.listen(self.engine, "checkout", checkout)
        event.listen(self.engine, "checkin", checkin)
        try:
            self.container.runs.list_runs()
            self.container.runs.list_runs(number="absent")
            with patch("threadsnap.services.run_dict_from_tasks", side_effect=RuntimeError("序列化失败")):
                with self.assertRaisesRegex(RuntimeError, "序列化失败"):
                    self.container.runs.list_runs()
            event.listen(self.engine, "before_cursor_execute", fail_groups)
            try:
                with self.assertRaisesRegex(RuntimeError, "查询失败夹具"):
                    self.container.runs.list_runs()
            finally:
                event.remove(self.engine, "before_cursor_execute", fail_groups)
            self.assertEqual(4, len(checked_out))
            self.assertEqual(checked_out, checked_in)
            self.assertEqual(0, self.engine.pool.checkedout())
            with self.container.sessions() as db:
                self.assertEqual(run_id, db.scalar(select(ExtractionRun.id)))
        finally:
            event.remove(self.engine, "checkout", checkout)
            event.remove(self.engine, "checkin", checkin)
