"""持久平台 FIFO、圈子验证和提取 Worker。"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from patchright.sync_api import sync_playwright
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from .collectors import AuthenticationRequired, CollectorFailure, DongchediCollector
from .models import (
    Circle,
    CircleTask,
    CommentSnapshot,
    ExtractionRun,
    PlatformConfig,
    PostSnapshot,
    ValidationJob,
    utc_now,
)
from .services import aggregate_run
from .session_store import SessionStore


class WorkerService:
    """一个协调线程按平台 FIFO 驱动持久任务。"""

    def __init__(
        self,
        factory: sessionmaker[Session],
        session_store: SessionStore,
        poll_seconds: float = 1.0,
    ):
        self.factory = factory
        self.session_store = session_store
        self.poll_seconds = poll_seconds
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.refresh_lock = threading.Lock()
        self.refresh_generation: dict[str, int] = {}

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.recover_interrupted()
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._loop, name="threadsnap-worker", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=10)

    def recover_interrupted(self) -> None:
        """进程重启时将未完成的运行中状态放回持久 FIFO。"""

        with self.factory.begin() as db:
            running_run_ids: set[str] = set()
            for task in db.scalars(select(CircleTask).where(CircleTask.status == "running")):
                task.status = "queued"
                task.started_at = None
                running_run_ids.add(task.run_id)
            for run_id in running_run_ids:
                run = db.get(ExtractionRun, run_id)
                if run and run.status == "running":
                    run.status = "queued"
                    run.started_at = None
            for job in db.scalars(select(ValidationJob).where(ValidationJob.status == "running")):
                job.status = "queued"
                job.started_at = None

    def _loop(self) -> None:
        while not self.stop_event.is_set():
            progressed = False
            try:
                progressed = self.process_once()
            except Exception:
                # 单轮异常不能结束持久 Worker；具体任务异常由任务分支记录。
                progressed = False
            if not progressed:
                self.stop_event.wait(self.poll_seconds)

    def process_once(self) -> bool:
        if self._process_validation_job():
            return True
        with self.factory() as db:
            platform_codes = list(
                db.scalars(
                    select(PlatformConfig.code)
                    .where(PlatformConfig.adapter_status == "available")
                    .order_by(PlatformConfig.code)
                )
            )
        for code in platform_codes:
            if self._process_platform_head(code):
                return True
        return False

    def _collector(
        self, platform: PlatformConfig, snapshot_concurrency: int | None = None
    ) -> DongchediCollector:
        if platform.code != "dongchedi":
            raise CollectorFailure("PLATFORM_NOT_INTEGRATED", f"{platform.display_name}暂未接入。")
        requested = snapshot_concurrency or platform.internal_concurrency
        concurrency = min(max(requested, platform.min_concurrency), platform.max_concurrency)
        return DongchediCollector(
            self.session_store.get_state(platform.code), concurrency=concurrency
        )

    def _process_validation_job(self) -> bool:
        with self.factory.begin() as db:
            job = db.scalar(
                select(ValidationJob)
                .where(ValidationJob.status == "queued")
                .order_by(ValidationJob.created_at)
                .limit(1)
            )
            if not job:
                return False
            circle = db.get(Circle, job.circle_id)
            platform = db.get(PlatformConfig, circle.platform_code) if circle else None
            if not circle or not platform:
                job.status = "failed"
                job.error_code = "CIRCLE_NOT_FOUND"
                job.error_message = "圈子配置已经不存在。"
                job.finished_at = utc_now()
                return True
            job.status = "running"
            job.started_at = utc_now()
            circle_id = circle.id
            circle_url = circle.url
            platform_code = platform.code
        try:
            with self.factory() as db:
                platform = db.get(PlatformConfig, platform_code)
                assert platform is not None
                result = self._collector(platform).validate_circle(circle_url)
        except AuthenticationRequired as exc:
            with self.factory.begin() as db:
                job = db.get(ValidationJob, job.id)
                circle = db.get(Circle, circle_id)
                if job:
                    job.status = "waiting_for_auth"
                    job.error_code = "AUTH_REQUIRED"
                    job.error_message = exc.message
                if circle:
                    circle.validation_status = "unverified"
                    circle.validation_error = exc.message
            return True
        except (CollectorFailure, Exception) as exc:
            code = exc.code if isinstance(exc, CollectorFailure) else "VALIDATION_FAILED"
            message = exc.message if isinstance(exc, CollectorFailure) else f"圈子验证失败：{exc}"
            with self.factory.begin() as db:
                job = db.get(ValidationJob, job.id)
                circle = db.get(Circle, circle_id)
                if job:
                    job.status = "failed"
                    job.error_code = code
                    job.error_message = message
                    job.finished_at = utc_now()
                if circle:
                    circle.validation_status = "failed"
                    circle.validation_error = message
            return True
        with self.factory.begin() as db:
            job = db.get(ValidationJob, job.id)
            circle = db.get(Circle, circle_id)
            if job:
                job.status = "success"
                job.result = result
                job.error_code = None
                job.error_message = None
                job.finished_at = utc_now()
            if circle:
                circle.name = result["name"]
                circle.url = result["url"]
                circle.validation_status = "verified"
                circle.validation_error = None
                circle.validated_at = utc_now()
                circle.adapter_version = result["adapter_version"]
        return True

    def _process_platform_head(self, platform_code: str) -> bool:
        with self.factory.begin() as db:
            if db.scalar(
                select(func.count())
                .select_from(CircleTask)
                .where(
                    CircleTask.platform_code == platform_code,
                    CircleTask.status == "waiting_for_auth",
                )
            ):
                return False
            head = db.scalar(
                select(CircleTask)
                .where(
                    CircleTask.platform_code == platform_code,
                    CircleTask.status == "queued",
                )
                .order_by(CircleTask.queue_sequence)
                .limit(1)
            )
            if not head:
                return False
            run = db.get(ExtractionRun, head.run_id)
            platform = db.get(PlatformConfig, platform_code)
            if not run or not platform:
                return False
            tasks = list(
                db.scalars(
                    select(CircleTask)
                    .where(
                        CircleTask.run_id == run.id,
                        CircleTask.platform_code == platform_code,
                        CircleTask.status == "queued",
                    )
                    .order_by(CircleTask.queue_sequence)
                )
            )
            for task in tasks:
                task.status = "running"
                task.started_at = task.started_at or utc_now()
            run.status = "running"
            run.started_at = run.started_at or utc_now()
            run_id = run.id
            concurrency = min(
                max(
                    int(
                        tasks[0].config_snapshot.get(
                            "internal_concurrency", platform.internal_concurrency
                        )
                    ),
                    platform.min_concurrency,
                ),
                platform.max_concurrency,
            )
        collector = self._collector(platform, concurrency)
        results: dict[str, dict[str, Any]] = {}
        with ThreadPoolExecutor(max_workers=min(concurrency, len(tasks))) as pool:
            futures = {
                pool.submit(self._execute_task, collector, task.id): task.id for task in tasks
            }
            for future in as_completed(futures):
                task_id = futures[future]
                try:
                    results[task_id] = future.result()
                except Exception as exc:
                    results[task_id] = {
                        "kind": "failed",
                        "code": "TASK_INTERNAL_ERROR",
                        "message": f"提取任务执行异常：{exc}",
                        "records": [],
                        "failures": [],
                    }
        with self.factory.begin() as db:
            run = db.get(ExtractionRun, run_id)
            assert run is not None
            for task_id, result in results.items():
                task = db.get(CircleTask, task_id)
                if task:
                    self._apply_result(db, task, result)
            aggregate_run(db, run)
        return True

    def _execute_task(self, collector: DongchediCollector, task_id: str) -> dict[str, Any]:
        with self.factory() as db:
            task = db.get(CircleTask, task_id)
            assert task is not None
            snapshot = dict(task.config_snapshot or {})
            circle_url = task.circle_url
            target = task.target_count
            transient = bool(snapshot.get("transient"))
            circle_id = task.circle_id
            known_urls = list(snapshot.get("known_post_urls") or [])
            completed_post_ids = set(
                db.scalars(
                    select(PostSnapshot.platform_post_id).where(
                        PostSnapshot.circle_task_id == task_id
                    )
                )
            )
            needs_validation = transient
            platform_code = task.platform_code
            if circle_id:
                circle = db.get(Circle, circle_id)
                needs_validation = bool(circle and circle.validation_status != "verified")
        validation = None
        generation = self.refresh_generation.get(platform_code, 0)
        try:
            if needs_validation:
                validation = collector.validate_circle(circle_url)
            remaining = max(0, target - len(completed_post_ids))
            payload = (
                collector.collect_urls(known_urls)
                if known_urls
                else collector.collect_circle(
                    circle_url, remaining, skip_post_ids=completed_post_ids
                )
            )
            return {"kind": "done", "validation": validation, **payload}
        except AuthenticationRequired as exc:
            trigger_url = exc.trigger_url or circle_url
            if self._refresh_after_auth(platform_code, trigger_url, generation):
                with self.factory() as db:
                    platform = db.get(PlatformConfig, platform_code)
                    assert platform is not None
                    refreshed = self._collector(platform, collector.concurrency)
                try:
                    if needs_validation and validation is None:
                        validation = refreshed.validate_circle(circle_url)
                    payload = (
                        refreshed.collect_urls(known_urls)
                        if known_urls
                        else refreshed.collect_circle(
                            circle_url,
                            remaining,
                            skip_post_ids=completed_post_ids,
                        )
                    )
                    return {"kind": "done", "validation": validation, **payload}
                except AuthenticationRequired as repeated:
                    exc = repeated
            return {
                "kind": "auth",
                "code": "AUTH_REQUIRED",
                "message": exc.message,
                "trigger_url": exc.trigger_url or trigger_url,
                "records": exc.records,
                "failures": exc.failures,
                "validation": validation,
            }
        except CollectorFailure as exc:
            return {
                "kind": "failed",
                "code": exc.code,
                "message": exc.message,
                "records": [],
                "failures": [],
                "validation": validation,
            }

    def _refresh_after_auth(
        self, platform_code: str, trigger_url: str, observed_generation: int
    ) -> bool:
        """同一认证失效事件只允许一个线程刷新服务器 Session。"""

        with self.refresh_lock:
            if self.refresh_generation.get(platform_code, 0) > observed_generation:
                return True
            state = self.session_store.get_state(platform_code)
            if not state:
                return False
            try:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(
                        headless=self.session_store.settings.auth_browser_headless
                    )
                    context = browser.new_context(
                        storage_state=state,
                        locale="zh-CN",
                        timezone_id=self.session_store.settings.timezone,
                    )
                    page = context.new_page()
                    page.goto(
                        trigger_url or "https://www.dongchedi.com/community/24729",
                        wait_until="domcontentloaded",
                        timeout=60_000,
                    )
                    page.wait_for_timeout(1000)
                    if "/login-required" in page.url:
                        context.close()
                        browser.close()
                        return False
                    refreshed_state = context.storage_state()
                    context.close()
                    browser.close()
                self.session_store.import_state(platform_code, refreshed_state)
                self.refresh_generation[platform_code] = observed_generation + 1
                return True
            except Exception:
                return False

    def _apply_result(self, db: Session, task: CircleTask, result: dict[str, Any]) -> None:
        validation = result.get("validation")
        if validation:
            circle = db.get(Circle, task.circle_id) if task.circle_id else None
            if not circle:
                circle = db.scalar(
                    select(Circle).where(
                        Circle.platform_code == task.platform_code,
                        Circle.external_id == task.external_id,
                    )
                )
            if not circle:
                circle = Circle(
                    platform_code=task.platform_code,
                    external_id=task.external_id,
                    url=validation["url"],
                    source_kind="manual_history",
                )
                db.add(circle)
                db.flush()
                task.circle_id = circle.id
            circle.name = validation["name"]
            circle.url = validation["url"]
            circle.validation_status = "verified"
            circle.validation_error = None
            circle.validated_at = utc_now()
            circle.adapter_version = validation["adapter_version"]
            circle.last_used_at = utc_now()
            task.circle_name = validation["name"]
            task.circle_url = validation["url"]
        records = result.get("records") or []
        existing = set(
            db.scalars(
                select(PostSnapshot.platform_post_id).where(PostSnapshot.circle_task_id == task.id)
            )
        )
        max_order = db.scalar(
            select(func.max(PostSnapshot.order_index)).where(PostSnapshot.circle_task_id == task.id)
        )
        next_order = (-1 if max_order is None else int(max_order)) + 1
        for record in records:
            if record["platform_post_id"] in existing:
                continue
            post = PostSnapshot(
                run_id=task.run_id,
                circle_task_id=task.id,
                platform_post_id=record["platform_post_id"],
                url=record["url"],
                title=record.get("title"),
                author=record.get("author"),
                published_at=record.get("published_at"),
                content=record.get("content"),
                image_urls=record.get("image_urls") or [],
                video_urls=record.get("video_urls") or [],
                reply_count=record.get("reply_count"),
                like_count=record.get("like_count"),
                section=record.get("section"),
                visibility=record.get("visibility", "unknown"),
                raw_status=record.get("raw_status"),
                order_index=next_order,
            )
            db.add(post)
            db.flush()
            next_order += 1
            for index, comment in enumerate(record.get("comments") or []):
                db.add(
                    CommentSnapshot(
                        post_id=post.id,
                        platform_comment_id=comment.get("platform_comment_id"),
                        author=comment.get("author"),
                        content=comment.get("content"),
                        published_at=comment.get("published_at"),
                        like_count=comment.get("like_count"),
                        order_index=index,
                    )
                )
            existing.add(record["platform_post_id"])
        task.completed_count = (
            db.scalar(
                select(func.count())
                .select_from(PostSnapshot)
                .where(PostSnapshot.circle_task_id == task.id)
            )
            or 0
        )
        task.failed_count = len(result.get("failures") or [])
        task.checkpoint = {
            "trigger_url": result.get("trigger_url"),
            "failed_urls": result.get("failures") or [],
            "completed_post_ids": sorted(existing),
        }
        if result["kind"] == "auth":
            task.status = "waiting_for_auth"
            task.error_code = result["code"]
            task.error_message = result["message"]
            task.stop_reason = None
        elif result["kind"] == "failed":
            task.status = "partial_success" if task.completed_count else "failed"
            task.error_code = result["code"]
            task.error_message = result["message"]
            task.stop_reason = result["message"]
            task.finished_at = utc_now()
        else:
            task.stop_reason = result.get("stop_reason")
            shortage_by_error = (
                task.completed_count < task.target_count
                and bool(result.get("failures"))
                and "没有更多" not in str(task.stop_reason)
            )
            task.status = (
                "partial_success"
                if shortage_by_error and task.completed_count
                else "failed"
                if shortage_by_error
                else "success"
            )
            task.error_code = "PARTIAL_RESULT" if shortage_by_error else None
            task.error_message = "部分候选帖子未能成功提取。" if shortage_by_error else None
            task.finished_at = utc_now()

    def resume_platform(self, platform_code: str) -> None:
        """认证状态更新后先恢复原等待任务和验证任务。"""

        with self.factory.begin() as db:
            for task in db.scalars(
                select(CircleTask).where(
                    CircleTask.platform_code == platform_code,
                    CircleTask.status == "waiting_for_auth",
                )
            ):
                task.status = "queued"
                task.error_code = None
                task.error_message = None
                run = db.get(ExtractionRun, task.run_id)
                if run:
                    run.status = "queued"
                    run.waiting_reason = None
            circle_ids = select(Circle.id).where(Circle.platform_code == platform_code)
            for job in db.scalars(
                select(ValidationJob).where(
                    ValidationJob.circle_id.in_(circle_ids),
                    ValidationJob.status == "waiting_for_auth",
                )
            ):
                job.status = "queued"
                job.error_code = None
                job.error_message = None
