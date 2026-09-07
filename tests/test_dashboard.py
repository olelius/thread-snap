"""首页聚合的范围、自然日边界、只读性与有界查询测试。"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import event

from tests.test_backend import AppCase
from threadsnap.dashboard import build_dashboard
from threadsnap.models import ExtractionRun, ReputationRun

NOW = datetime(2026, 9, 7, 2, tzinfo=timezone.utc)


class DashboardTests(AppCase):
    def add_extraction(self, db, index, *, trigger="manual", status="success", created=NOW):
        """直接建立领域快照，避免启动采集器。"""
        db.add(
            ExtractionRun(
                id=f"extract-{index}",
                number=f"EX-{index:04d}",
                trigger_type=trigger,
                status=status,
                idempotency_scope="dashboard-test",
                idempotency_key=str(index),
                request_hash="fixture",
                created_at=created,
                planned_count=10,
                completed_count=10 if status == "success" else 0,
                config_snapshot={"never_expose": "private-fixture"},
            )
        )

    def add_reputation(self, db, index, *, source="scheduled", date="2026-09-07", status="success"):
        """正式、验收、补跑和合成记录分开构造。"""
        db.add(
            ReputationRun(
                id=f"reputation-{index}",
                number=f"RP-{index:04d}",
                source_type=source,
                planned_date=date,
                run_type="daily",
                status=status,
                created_at=NOW,
                report_path="private-fixture-path",
                report_text="private-fixture-report",
            )
        )

    def dashboard(self):
        return build_dashboard(self.container.sessions, "Asia/Shanghai", NOW)

    def test_empty_endpoint_and_no_pagination_parameters(self):
        response = self.client.get("/api/v1/dashboard?limit=1&page=10")
        self.assertEqual(200, response.status_code)
        data = response.json()
        self.assertEqual("Asia/Shanghai", data["timezone"])
        self.assertEqual(
            ["extraction", "recurring", "reputation"], [c["key"] for c in data["categories"]]
        )
        for item in data["categories"]:
            self.assertEqual(
                (0, 0, 0, 0), tuple(item[key] for key in ["total", "today", "active", "attention"])
            )
            self.assertEqual([], item["recent"])
            self.assertEqual([], item["attention_items"])

    def test_counts_cover_all_records_but_recent_and_attention_are_bounded(self):
        with self.container.sessions.begin() as db:
            for index in range(65):
                self.add_extraction(db, index, status="failed" if index < 12 else "success")
            for index in range(65, 70):
                self.add_extraction(db, index, trigger="scheduled", status="queued")
            for index in range(70, 74):
                self.add_extraction(db, index, trigger="recurring", status="waiting_for_auth")
            self.add_extraction(db, 74, trigger="unknown")
        normal, recurring, reputation = self.dashboard()["categories"]
        self.assertEqual(
            (70, 70, 5, 12), tuple(normal[key] for key in ["total", "today", "active", "attention"])
        )
        self.assertEqual(8, len(normal["recent"]))
        self.assertEqual(3, len(normal["attention_items"]))
        self.assertEqual(
            (4, 4, 4), (recurring["total"], recurring["active"], recurring["attention"])
        )
        self.assertEqual(0, reputation["total"])
        # 相同时间仍使用稳定ID倒序，而不是数据库未定义的自然顺序。
        self.assertEqual(
            sorted([item["id"] for item in normal["recent"]], reverse=True),
            [item["id"] for item in normal["recent"]],
        )

    def test_today_uses_shanghai_half_open_creation_window(self):
        start = datetime(2026, 9, 6, 16, tzinfo=timezone.utc)
        with self.container.sessions.begin() as db:
            for index, stamp in enumerate(
                [
                    start - timedelta(microseconds=1),
                    start,
                    start + timedelta(days=1, microseconds=-1),
                    start + timedelta(days=1),
                ]
            ):
                self.add_extraction(db, index, created=stamp)
        data = self.dashboard()
        self.assertEqual("2026-09-07", data["date"])
        self.assertEqual(4, data["categories"][0]["total"])
        self.assertEqual(2, data["categories"][0]["today"])

    def test_reputation_plan_date_and_root_scope(self):
        with self.container.sessions.begin() as db:
            self.add_reputation(db, 1, status="running")
            self.add_reputation(db, 2, date="2026-09-06", status="partial_success")
            self.add_reputation(db, 3, source="real_acceptance")
            self.add_reputation(db, 4, source="retry", status="failed")
            self.add_reputation(db, 5, source="synthetic", status="failed")
        item = self.dashboard()["categories"][2]
        self.assertEqual(
            (3, 2, 1, 1), tuple(item[key] for key in ["total", "today", "active", "attention"])
        )
        self.assertEqual("planned_date", item["today_basis"])
        self.assertEqual(
            {"reputation-1", "reputation-2", "reputation-3"}, {r["id"] for r in item["recent"]}
        )

    def test_endpoint_exposes_only_summary_and_does_not_write(self):
        with self.container.sessions.begin() as db:
            self.add_extraction(db, 1)
            self.add_reputation(db, 1)
        statements = []

        def observe(_conn, _cursor, statement, _params, _ctx, _many):
            statements.append(statement.strip().split()[0].upper())

        event.listen(self.container.engine, "before_cursor_execute", observe)
        try:
            response = self.client.get("/api/v1/dashboard")
        finally:
            event.remove(self.container.engine, "before_cursor_execute", observe)
        self.assertEqual(200, response.status_code)
        self.assertEqual(9, statements.count("SELECT"))
        self.assertFalse(set(statements) & {"UPDATE", "INSERT", "DELETE"})
        for private in [
            "private-fixture",
            "config_snapshot",
            "report_path",
            "report_text",
            "request_hash",
            "idempotency_key",
        ]:
            self.assertNotIn(private, response.text)

    def test_rejects_naive_reference_time(self):
        with self.assertRaises(ValueError):
            build_dashboard(self.container.sessions, "Asia/Shanghai", datetime(2026, 9, 7))
