"""多平台历史批次补提的 API、SQLite 与正式 Worker 定向回归。"""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

from sqlalchemy import func, select
from test_backend import AppCase, sample_record

from threadsnap.models import CircleTask, ExtractionRun, PlatformConfig, PostSnapshot


class MultiplatformRetryTests(AppCase):
    """只使用三个平台的有限记录，不访问平台、模型或截图服务。"""

    def _seed_original(self, *, mixed_branches: bool = False) -> tuple[str, dict]:
        """保存三来源五候选：懂车帝完整，其余平台各一成功、一缺失。"""

        specs = {
            "dongchedi": ("https://www.dongchedi.com/community/24729", "7001", "7002"),
            "autohome": ("https://club.autohome.com.cn/bbs/forum-c-100-1.html", "8001", "8002"),
            "yiche": ("https://baa.yiche.com/sample/", "9001", "9002"),
        }
        sources = {}
        with self.container.sessions.begin() as db:
            run = ExtractionRun(
                number="20260915-083501-001",
                trigger_type="scheduled",
                status="partial_success",
                planned_count=5,
                completed_count=3,
                failed_count=2,
                idempotency_scope="test",
                idempotency_key="multiplatform-original",
                request_hash="a" * 64,
            )
            db.add(run)
            db.flush()
            for index, (code, (circle_url, completed_id, missing_id)) in enumerate(specs.items()):
                platform = db.get(PlatformConfig, code)
                platform.enabled = True
                platform.adapter_status = "available"
                urls = [
                    f"https://{code}.example.test/posts/{item}"
                    for item in (completed_id, missing_id)
                ]
                source_index = 7 + index
                config = {
                    "quantity": 1 if index == 0 else 2,
                    "internal_concurrency": 1,
                    "vehicle_name": f"车型-{code}",
                    "source_name": f"来源-{code}",
                    "ai_analysis_enabled": code == "autohome",
                    "ai_account_id": index + 1,
                    "ai_account_name": f"账户-{code}",
                    "screenshot_enabled": code == "autohome",
                    "source_rules": [{"id": index + 1, "version": index + 2}],
                }
                checkpoint = (
                    {
                        "failed_urls": [
                            {"url": urls[1], "code": "POST_NOT_FOUND", "source_index": source_index}
                        ]
                    }
                    if index
                    else {}
                )
                if mixed_branches and code == "autohome":
                    config.update(
                        known_post_urls=urls, source_indexes={urls[0]: 0, urls[1]: source_index}
                    )
                    checkpoint = {"failed_urls": []}
                elif mixed_branches and code == "yiche":
                    checkpoint = {"failed_urls": []}
                task = CircleTask(
                    run_id=run.id,
                    platform_code=code,
                    external_id=f"circle-{index}",
                    circle_name=f"来源-{code}",
                    circle_url=circle_url,
                    section="dynamic" if index == 0 else "forum",
                    list_order="latest_publish" if index == 2 else "latest_reply",
                    status="success" if index == 0 else "partial_success",
                    queue_sequence=index + 1,
                    source_position=index * 4,
                    target_count=1 if index == 0 else 2,
                    completed_count=1,
                    failed_count=0 if index == 0 else 1,
                    config_snapshot=config,
                    checkpoint=checkpoint,
                )
                db.add(task)
                db.flush()
                db.add(
                    PostSnapshot(
                        run_id=run.id,
                        circle_task_id=task.id,
                        platform_post_id=completed_id,
                        url=urls[0],
                        title=f"原结果-{code}",
                        content="原批次正文",
                        order_index=0,
                    )
                )
                sources[code] = {
                    "task_id": task.id,
                    "circle_url": circle_url,
                    "urls": urls,
                    "completed_id": completed_id,
                    "missing_id": missing_id,
                    "source_index": source_index,
                    "source_position": index * 4,
                    "section": task.section,
                    "list_order": task.list_order,
                    "config": config,
                }
            return run.id, sources

    def _history(self, run_id: str) -> list:
        """按原始表列比较历史对象，避免关联视图计数掩盖快照变动。"""

        with self.container.sessions() as db:
            return deepcopy(
                [
                    [
                        dict(row)
                        for row in db.execute(
                            select(model.__table__)
                            .where(
                                model.id == run_id
                                if model is ExtractionRun
                                else model.run_id == run_id
                            )
                            .order_by(model.id)
                        ).mappings()
                    ]
                    for model in (ExtractionRun, CircleTask, PostSnapshot)
                ]
            )

    def _retry(self, run_id: str, key: str = "multiplatform-retry-0001"):
        return self.client.post(f"/api/v1/runs/{run_id}/retry", headers={"Idempotency-Key": key})

    def _run_worker(self, sources: dict) -> list:
        """仅替换外部采集边界；持久领取、分平台调度、入库和聚合走正式实现。"""

        calls = []
        owner = self

        class Collector:
            def __init__(self, platform_code: str):
                self.platform_code = platform_code

            def collect_urls(self, urls: list[str], on_progress=None) -> dict:
                owner.assertEqual([sources[self.platform_code]["urls"][1]], urls)
                calls.append((self.platform_code, "urls", list(urls)))
                records = []
                for url in urls:
                    record = sample_record(url.rsplit("/", 1)[-1])
                    record["url"] = url
                    records.append(record)
                    if on_progress:
                        on_progress(record, None)
                return {"records": records, "failures": [], "stop_reason": "固定样本完成。"}

            def collect_circle(
                self, url: str, target: int, skip_post_ids=None, on_progress=None
            ) -> dict:
                source = sources[self.platform_code]
                owner.assertEqual(
                    (source["circle_url"], 1, {source["completed_id"]}),
                    (url, target, skip_post_ids),
                )
                calls.append((self.platform_code, "circle", url))
                record = sample_record(source["missing_id"])
                record.update(url=source["urls"][1], order_index=source["source_index"])
                if on_progress:
                    on_progress(record, None)
                return {"records": [record], "failures": [], "stop_reason": "来源缺口完成。"}

        worker = self.container.worker
        worker._collector = lambda platform, *_args: Collector(platform.code)
        worker.screenshot_service = None
        worker.sentiment_service = SimpleNamespace(enqueue_for_post=Mock())
        self.assertTrue(worker.process_once())
        self.assertFalse(worker.process_once())
        self.assertEqual(2, len(calls))
        self.assertEqual({"autohome", "yiche"}, {call[0] for call in calls})
        received = {
            call.args[2]: (
                call.kwargs["account_id"],
                call.kwargs["account_name"],
                call.kwargs["analysis_enabled"],
            )
            for call in worker.sentiment_service.enqueue_for_post.call_args_list
        }
        self.assertEqual(
            {"autohome": (2, "账户-autohome", True), "yiche": (3, "账户-yiche", False)}, received
        )
        return calls

    def test_failed_urls_retry_runs_each_platform_once_and_preserves_history(self) -> None:
        """一个按钮产生一个关联批次；原三条成功快照不重采、不改写。"""

        run_id, sources = self._seed_original()
        before = self._history(run_id)
        response = self._retry(run_id)
        self.assertEqual(202, response.status_code, response.text)
        retry = response.json()
        self.assertEqual(run_id, retry["related_run_id"])
        self.assertEqual(("manual", 2), (retry["trigger_type"], retry["planned_count"]))
        with self.container.sessions() as db:
            tasks = list(
                db.scalars(
                    select(CircleTask)
                    .where(CircleTask.run_id == retry["id"])
                    .order_by(CircleTask.queue_sequence)
                )
            )
            self.assertEqual(["autohome", "yiche"], [task.platform_code for task in tasks])
            for task in tasks:
                source = sources[task.platform_code]
                self.assertEqual(
                    (source["source_position"], source["section"], source["list_order"]),
                    (task.source_position, task.section, task.list_order),
                )
                self.assertEqual(source["circle_url"], task.circle_url)
                self.assertEqual(source["task_id"], task.config_snapshot["retry_of_task_id"])
                self.assertEqual([source["urls"][1]], task.config_snapshot["known_post_urls"])
                self.assertEqual(
                    {source["urls"][1]: source["source_index"]},
                    task.config_snapshot["source_indexes"],
                )
                for field, value in source["config"].items():
                    self.assertEqual(value, task.config_snapshot[field], field)
        self._run_worker(sources)
        finished = self.container.runs.get_run(retry["id"])
        self.assertEqual(
            ("success", 2, 0),
            (finished["status"], finished["completed_count"], finished["failed_count"]),
        )
        with self.container.sessions() as db:
            rows = db.execute(
                select(
                    CircleTask.platform_code,
                    PostSnapshot.platform_post_id,
                    PostSnapshot.order_index,
                )
                .join(PostSnapshot, PostSnapshot.circle_task_id == CircleTask.id)
                .where(CircleTask.run_id == retry["id"])
            ).all()
            self.assertEqual({("autohome", "8002", 8), ("yiche", "9002", 9)}, set(rows))
        again = self._retry(run_id)
        self.assertEqual(202, again.status_code, again.text)
        self.assertEqual(retry["id"], again.json()["id"])
        self.assertTrue(again.json()["already_submitted"])
        self.assertEqual(before, self._history(run_id))
        self.assertEqual(5, self.container.runs.posts(retry["id"])["total"])

    def test_known_urls_and_circle_failure_keep_distinct_platforms(self) -> None:
        """无逐URL失败记录的两个回退分支仍保存各自的平台与来源。"""

        run_id, sources = self._seed_original(mixed_branches=True)
        response = self._retry(run_id)
        self.assertEqual(202, response.status_code, response.text)
        with self.container.sessions() as db:
            tasks = {
                task.platform_code: task
                for task in db.scalars(
                    select(CircleTask).where(CircleTask.run_id == response.json()["id"])
                )
            }
            self.assertEqual({"autohome", "yiche"}, set(tasks))
            self.assertEqual(
                [sources["autohome"]["urls"][1]],
                tasks["autohome"].config_snapshot["known_post_urls"],
            )
            self.assertEqual(
                {sources["autohome"]["urls"][1]: 8},
                tasks["autohome"].config_snapshot["source_indexes"],
            )
            self.assertEqual(["9001"], tasks["yiche"].config_snapshot["skip_post_ids"])
            self.assertNotIn("known_post_urls", tasks["yiche"].config_snapshot)
            self.assertEqual(
                [4, 8], [tasks[code].source_position for code in ("autohome", "yiche")]
            )
        calls = self._run_worker(sources)
        self.assertEqual(
            {("autohome", "urls"), ("yiche", "circle")}, {(code, mode) for code, mode, _ in calls}
        )
        self.assertEqual("success", self.container.runs.get_run(response.json()["id"])["status"])

    def test_disabled_platform_without_remaining_items_does_not_block(self) -> None:
        """已补满但旧状态仍非success的停用平台不应被误计为本次目标。"""

        run_id, sources = self._seed_original()
        with self.container.sessions.begin() as db:
            db.get(PlatformConfig, "dongchedi").enabled = False
            db.get(CircleTask, sources["dongchedi"]["task_id"]).status = "partial_success"
        response = self._retry(run_id)
        self.assertEqual(202, response.status_code, response.text)
        self.assertEqual({"autohome", "yiche"}, set(response.json()["platform_codes"]))
        self.assertEqual(2, response.json()["planned_count"])

    def test_disabled_selected_platform_rejects_atomically_with_platform_name(self) -> None:
        """任一实际补提平台停用时整次不落新批次或任务，错误标明平台。"""

        run_id, _sources = self._seed_original()
        before = self._history(run_id)
        with self.container.sessions.begin() as db:
            db.get(PlatformConfig, "yiche").enabled = False
        response = self._retry(run_id)
        self.assertEqual(409, response.status_code, response.text)
        self.assertIn("PLATFORM_DISABLED", response.text)
        self.assertIn("易车", response.text)
        with self.container.sessions() as db:
            self.assertEqual(1, db.scalar(select(func.count()).select_from(ExtractionRun)))
            self.assertEqual(3, db.scalar(select(func.count()).select_from(CircleTask)))
        self.assertEqual(before, self._history(run_id))
