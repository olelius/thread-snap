"""几何失稳通过正式 Worker 持久续作，离线验证原页和已完成帖子不会重取。"""

from __future__ import annotations

import hashlib
import io
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image
from sqlalchemy import select
from test_backend import AppCase, FakeCollector, sample_record

from threadsnap.collectors.base import CollectorFailure
from threadsnap.collectors.dongchedi import DongchediCollector
from threadsnap.models import CirclePageEvidence, CircleTask, PostSnapshot
from threadsnap.schemas import ManualRunCreate
from threadsnap.worker import (
    BATCH_RETRY_WAVE_KEY,
    GEOMETRY_RETRYABLE_SOURCE_FAILURE_CODES,
    _retry_delay_seconds,
)


def page_payload(page_number: int) -> dict:
    """生成只用于隔离数据库的同次几何清单与 PNG，不发起网页请求。"""

    stream = io.BytesIO()
    Image.new("RGB", (120, 100), "white").save(stream, format="PNG")
    return {
        "page_number": page_number,
        "exact_url": "https://www.dongchedi.com/community/24729",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "adapter_version": DongchediCollector.adapter_version,
        "browser_version": "offline-worker-fixture",
        "viewport": {"width": 120, "height": 100, "device_scale_factor": 1},
        "document": {"width": 120, "height": 100},
        "list_schema_version": "circle-page-v2-bound-geometry",
        "capture_geometry": {
            "schema": "threadsnap.capture-geometry.v1",
            "coordinate_space": "document-css-px",
            "device_scale_factor": 1,
            "png_size": {"width": 120, "height": 100},
            "before_sha256": "a" * 64,
            "after_sha256": "a" * 64,
            "scrollbar_policy": "native-hidden",
            "layout_viewport": {"width": 120, "height": 100},
        },
        "screenshot": stream.getvalue(),
        "rows": [
            {
                "post_id": str(1000 + page_number),
                "url": f"https://www.dongchedi.com/ugc/article/{1000 + page_number}",
                "order_index": 0,
                "text": "冻结页面",
                "image_count": 0,
                "rect": {"x": 10, "y": 20, "width": 80, "height": 30},
            }
        ],
    }


class CaptureGeometryRetryTests(AppCase):
    def test_geometry_retries_preserve_posts_and_reuse_persisted_pages(self) -> None:
        """两种几何错误都回到FIFO；正式collect_circle复用第一页面清单直到第二页成功。"""

        circle = self.save_verified_circle()
        for index, error_code in enumerate(sorted(GEOMETRY_RETRYABLE_SOURCE_FAILURE_CODES)):
            with self.subTest(error_code=error_code):
                run = self.container.runs.create_manual(
                    ManualRunCreate(
                        platform_code="dongchedi",
                        circle_ids=[circle.id],
                        quantity=2,
                        ai_analysis_enabled=False,
                        screenshot_enabled=True,
                    ),
                    scope="api",
                    header_key=f"geometry-retry-{index}",
                )
                capture_calls: list[int] = []
                post_calls: list[str] = []

                class CaptureCollector(FakeCollector):
                    supports_page_evidence = True
                    collect_circle = DongchediCollector.collect_circle

                    def capture_circle_page(self, _url: str, page_number: int) -> dict:
                        capture_calls.append(page_number)
                        if page_number == 2 and capture_calls.count(2) == 1:
                            raise CollectorFailure(error_code, "页面几何暂时变化。")
                        return page_payload(page_number)

                    def fetch_post(self, url: str) -> dict:
                        post_calls.append(url)
                        return sample_record(url.rsplit("/", 1)[-1])

                collector = CaptureCollector()
                self.container.worker._collector = lambda *_args: collector
                self.assertTrue(self.container.worker.process_once())
                waiting = self.container.runs.get_run(run["id"])
                self.assertEqual(
                    ("queued", 1, 0),
                    tuple(waiting[key] for key in ("status", "completed_count", "failed_count")),
                )
                with self.container.sessions.begin() as db:
                    task = db.scalar(select(CircleTask).where(CircleTask.run_id == run["id"]))
                    self.assertIsNotNone(task)
                    self.assertIsNone(task.error_code)
                    self.assertIsNone(task.finished_at)
                    self.assertIn("页面布局稳定中", task.stop_reason)
                    self.assertEqual("source", task.checkpoint["retry_scope"])
                    self.assertEqual([], task.checkpoint["retry_urls"])
                    self.assertNotIn(BATCH_RETRY_WAVE_KEY, task.checkpoint)
                    evidence = db.scalar(
                        select(CirclePageEvidence).where(
                            CirclePageEvidence.circle_task_id == task.id
                        )
                    )
                    first_page_id = evidence.id
                    first_page_path = Path(evidence.screenshot_path)
                    first_page_sha = hashlib.sha256(first_page_path.read_bytes()).hexdigest()
                    future = datetime.now(timezone.utc) + timedelta(seconds=60)
                    task.checkpoint = {**task.checkpoint, "retry_not_before": future.isoformat()}
                # 全局轮询还可能生成前一来源成果，这里只断言来源FIFO未到期不领取。
                self.assertFalse(self.container.worker._process_platform_head("dongchedi"))
                self.assertEqual([1, 2], capture_calls)
                with self.container.sessions.begin() as db:
                    task = db.scalar(select(CircleTask).where(CircleTask.run_id == run["id"]))
                    task.checkpoint = {
                        **task.checkpoint,
                        "retry_not_before": datetime.now(timezone.utc).isoformat(),
                    }
                self.assertTrue(self.container.worker.process_once())
                completed = self.container.runs.get_run(run["id"])
                self.assertEqual(
                    ("success", 2, 0),
                    tuple(completed[key] for key in ("status", "completed_count", "failed_count")),
                )
                self.assertEqual([1, 2, 2], capture_calls)
                self.assertEqual(
                    [
                        "https://www.dongchedi.com/ugc/article/1001",
                        "https://www.dongchedi.com/ugc/article/1002",
                    ],
                    post_calls,
                )
                with self.container.sessions() as db:
                    task = db.scalar(select(CircleTask).where(CircleTask.run_id == run["id"]))
                    pages = list(
                        db.scalars(
                            select(CirclePageEvidence).where(
                                CirclePageEvidence.circle_task_id == task.id
                            )
                        )
                    )
                    self.assertEqual(2, len(pages))
                    self.assertIn(first_page_id, [item.id for item in pages])
                    self.assertEqual(
                        2,
                        len(
                            list(
                                db.scalars(
                                    select(PostSnapshot).where(
                                        PostSnapshot.circle_task_id == task.id
                                    )
                                )
                            )
                        ),
                    )
                self.assertEqual(
                    first_page_sha, hashlib.sha256(first_page_path.read_bytes()).hexdigest()
                )
                self.assertEqual(
                    [2, 4, 8, 16, 32, 60, 60],
                    [_retry_delay_seconds(error_code, attempt) for attempt in range(1, 8)],
                )

    def test_other_contract_errors_and_batch_retry_budget_remain_terminal(self) -> None:
        """仅几何暂态可恢复；几何续作不刷新列表响应缺失的单波复访额度。"""

        circle = self.save_verified_circle()
        run = self.container.runs.create_manual(
            ManualRunCreate(
                platform_code="dongchedi",
                circle_ids=[circle.id],
                quantity=1,
                ai_analysis_enabled=False,
                screenshot_enabled=False,
            ),
            scope="api",
            header_key="geometry-retry-boundary",
        )
        with self.container.sessions() as db:
            task_id = db.scalar(select(CircleTask.id).where(CircleTask.run_id == run["id"]))

        class BrokenCollector(FakeCollector):
            code = ""

            def collect_circle(self, *_args, **_kwargs) -> dict:
                raise CollectorFailure(self.code, "保留明确错误。")

        collector = BrokenCollector()
        for code in (
            "PAGE_EVIDENCE_LIST_MISMATCH",
            "PAGE_EVIDENCE_CORRUPTED",
            "PAGE_EVIDENCE_LAYOUT_INVALID",
            "UNKNOWN_GEOMETRY_CONTRACT",
        ):
            collector.code = code
            result = self.container.worker._execute_task(collector, task_id)
            self.assertEqual(("failed", code), (result["kind"], result["code"]))
        with self.container.sessions.begin() as db:
            task = db.get(CircleTask, task_id)
            task.checkpoint = {BATCH_RETRY_WAVE_KEY: True}
        collector.code = "PAGE_EVIDENCE_LAYOUT_UNSTABLE"
        result = self.container.worker._execute_task(collector, task_id)
        self.assertEqual("retry", result["kind"])
        with self.container.sessions.begin() as db:
            task = db.get(CircleTask, task_id)
            self.container.worker._apply_result(db, task, result)
            self.assertTrue(task.checkpoint[BATCH_RETRY_WAVE_KEY])
        collector.code = "PAGE_EVIDENCE_LIST_RESPONSE_MISSING"
        result = self.container.worker._execute_task(collector, task_id)
        self.assertEqual("failed", result["kind"])
