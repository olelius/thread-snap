"""持久平台 FIFO、圈子验证和提取 Worker。"""

from __future__ import annotations

import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from inspect import signature
from time import monotonic
from typing import Any, Callable
from urllib.parse import urlsplit

from patchright.sync_api import sync_playwright
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from .browser_runtime import browser_launch_args
from .collectors import AuthenticationRequired, Collector, CollectorFailure, get_platform_spec
from .errors import DomainError
from .models import (
    Circle,
    CircleTask,
    CommentSnapshot,
    ExtractionRun,
    PlatformConfig,
    PostSnapshot,
    ReputationRun,
    ValidationJob,
    utc_now,
)
from .screenshots import ScreenshotService
from .sentiment import SentimentService, deduplicate_media_urls
from .services import aggregate_run, related_run_ids
from .session_store import SessionStore


def _supports_page_evidence(collector: Collector) -> bool:
    """同时核对能力声明与调用签名，避免把截图回调传给旧适配器。"""

    return bool(getattr(collector, "supports_page_evidence", False)) and (
        "on_page_evidence" in signature(collector.collect_circle).parameters
    )


class WorkerService:
    """一个协调线程按平台 FIFO 驱动持久任务。"""

    def __init__(
        self,
        factory: sessionmaker[Session],
        session_store: SessionStore,
        poll_seconds: float = 1.0,
        event_publisher: Callable[..., Any] | None = None,
        sentiment_service: SentimentService | None = None,
        screenshot_service: ScreenshotService | None = None,
    ):
        self.factory = factory
        self.session_store = session_store
        self.poll_seconds = poll_seconds
        self.event_publisher = event_publisher
        self.sentiment_service = sentiment_service
        self.screenshot_service = screenshot_service
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.refresh_lock = threading.Lock()
        self.refresh_generation: dict[str, int] = {}
        self.media_resolution_lock = threading.Lock()
        self.media_url_cache: dict[str, tuple[float, dict[str, Any]]] = {}

    def resolve_post_video_urls(self, run_id: str, post_id: str) -> dict[str, Any]:
        """按需解析临时播放 URL，不改写不可变帖子快照。"""

        with self.factory() as db:
            if not db.get(ExtractionRun, run_id):
                raise DomainError("RUN_NOT_FOUND", "指定提取批次不存在。", status_code=404)
            post = db.get(PostSnapshot, post_id)
            if not post or post.run_id not in related_run_ids(db, run_id):
                raise DomainError("POST_NOT_FOUND", "指定帖子快照不存在。", status_code=404)
            task = db.get(CircleTask, post.circle_task_id)
            platform_code = task.platform_code if task else None
            raw_status = post.raw_status if isinstance(post.raw_status, dict) else {}
            video_id = str(raw_status.get("video_id") or "").strip()
        if not platform_code:
            raise DomainError(
                "MEDIA_RESOLVER_UNAVAILABLE",
                "帖子快照缺少平台任务，不能刷新视频地址。",
                status_code=409,
            )
        spec = get_platform_spec(platform_code)
        if not spec.supports_live_video_resolution:
            raise DomainError(
                "MEDIA_RESOLVER_UNAVAILABLE",
                "当前平台尚未接入视频播放地址刷新。",
                status_code=409,
            )

        cached = self.media_url_cache.get(post_id)
        now_tick = monotonic()
        if cached and cached[0] > now_tick:
            return dict(cached[1])
        with self.media_resolution_lock:
            cached = self.media_url_cache.get(post_id)
            now_tick = monotonic()
            if cached and cached[0] > now_tick:
                return dict(cached[1])
            try:
                if not video_id:
                    raise DomainError(
                        "MEDIA_URL_NOT_FOUND",
                        "帖子快照没有可用于刷新播放地址的视频 ID，请打开原帖查看。",
                        status_code=404,
                    )
                collector = spec.create_background_collector(
                    self.session_store.get_state(platform_code),
                    concurrency=1,
                )
                resolver = getattr(collector, "resolve_video_urls", None)
                if resolver is None:
                    raise DomainError(
                        "MEDIA_RESOLVER_UNAVAILABLE",
                        "当前平台尚未接入视频播放地址刷新。",
                        status_code=409,
                    )
                urls = deduplicate_media_urls(resolver(video_id))
            except DomainError:
                raise
            except Exception as exc:
                raise DomainError(
                    "MEDIA_URL_REFRESH_FAILED",
                    "视频播放地址刷新失败，请稍后重试或打开原帖。",
                    status_code=502,
                    details=[{"reason": type(exc).__name__}],
                ) from exc
            if not urls:
                raise DomainError(
                    "MEDIA_URL_NOT_FOUND",
                    "原帖当前没有返回可播放的视频地址，请打开原帖查看。",
                    status_code=404,
                )
            expiries = [value for url in urls if (value := playback_url_expiry(url))]
            expires_at = min(expiries) if expiries else None
            now = utc_now()
            ttl_seconds = 300.0
            if expires_at:
                ttl_seconds = max(1.0, min(2700.0, (expires_at - now).total_seconds() - 60.0))
            result = {
                "video_urls": urls,
                "expires_at": expires_at.isoformat() if expires_at else None,
                "source": "live_url",
            }
            if len(self.media_url_cache) >= 256:
                self.media_url_cache.pop(next(iter(self.media_url_cache)))
            self.media_url_cache[post_id] = (now_tick + ttl_seconds, result)
            return dict(result)

    def cached_post_video_url(self, run_id: str, post_id: str, index: int) -> str:
        """返回用户刚刚显式解析的播放 URL，不在媒体请求中再次访问平台。"""

        with self.factory() as db:
            if not db.get(ExtractionRun, run_id):
                raise DomainError("RUN_NOT_FOUND", "指定提取批次不存在。", status_code=404)
            post = db.get(PostSnapshot, post_id)
            if not post or post.run_id not in related_run_ids(db, run_id):
                raise DomainError("POST_NOT_FOUND", "指定帖子快照不存在。", status_code=404)
        cached = self.media_url_cache.get(post_id)
        if not cached or cached[0] <= monotonic():
            raise DomainError(
                "MEDIA_URL_EXPIRED",
                "视频播放地址已过期，请重新点击加载视频。",
                status_code=410,
            )
        urls = cached[1]["video_urls"]
        if index < 0 or index >= len(urls):
            raise DomainError("MEDIA_URL_NOT_FOUND", "指定视频不存在。", status_code=404)
        return str(urls[index])

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
        if not self._official_reputation_waiting() and self._process_validation_job():
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
        if self.screenshot_service and self.screenshot_service.process_once():
            return True
        return False

    def _collector(
        self, platform: PlatformConfig, snapshot_concurrency: int | None = None
    ) -> Collector:
        spec = get_platform_spec(platform.code)
        requested = snapshot_concurrency or platform.internal_concurrency
        concurrency = min(max(requested, platform.min_concurrency), platform.max_concurrency)
        return spec.create_background_collector(
            self.session_store.get_state(platform.code),
            concurrency=concurrency,
        )

    def _process_validation_job(self) -> bool:
        missing = False
        with self.factory.begin() as db:
            job = db.scalar(
                select(ValidationJob)
                .where(ValidationJob.status == "queued")
                .order_by(ValidationJob.created_at)
                .limit(1)
            )
            if not job:
                return False
            job_id = job.id
            circle_id = job.circle_id
            circle = db.get(Circle, job.circle_id)
            platform = db.get(PlatformConfig, circle.platform_code) if circle else None
            if not circle or not platform:
                job.status = "failed"
                job.error_code = "CIRCLE_NOT_FOUND"
                job.error_message = "圈子配置已经不存在。"
                job.finished_at = utc_now()
                missing = True
            else:
                if platform.adapter_status != "available":
                    job.status = "failed"
                    job.error_code = "PLATFORM_NOT_INTEGRATED"
                    job.error_message = "该平台尚未通过接入验收。"
                    job.finished_at = utc_now()
                    circle.validation_status = "unverified"
                    circle.validation_error = job.error_message
                    missing = True
                else:
                    job.status = "running"
                    job.started_at = utc_now()
                    circle_url = circle.url
                    platform_code = platform.code
        if missing:
            self._publish_validation(circle_id, job_id, "failed")
            return True
        try:
            with self.factory() as db:
                platform = db.get(PlatformConfig, platform_code)
                assert platform is not None
                result = self._collector(platform).validate_circle(circle_url)
        except AuthenticationRequired as exc:
            spec = get_platform_spec(platform_code)
            with self.factory.begin() as db:
                job = db.get(ValidationJob, job.id)
                circle = db.get(Circle, circle_id)
                if job and spec.supports_authentication:
                    job.status = "waiting_for_auth"
                    job.error_code = "AUTH_REQUIRED"
                    job.error_message = exc.message
                elif job:
                    job.status = "failed"
                    job.error_code = "AUTH_MODE_UNSUPPORTED"
                    job.error_message = "该平台尚未建立已验证的认证流程。"
                    job.finished_at = utc_now()
                if circle:
                    circle.validation_status = "unverified"
                    circle.validation_error = (
                        exc.message
                        if spec.supports_authentication
                        else "该平台尚未建立已验证的认证流程。"
                    )
            status = "waiting_for_auth" if spec.supports_authentication else "failed"
            self._publish_validation(circle_id, job_id, status)
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
            self._publish_validation(circle_id, job_id, "failed")
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
                completed_at = utc_now()
                first_validation = circle.first_validated_at is None
                circle.name = result["name"]
                circle.url = result["url"]
                circle.list_order = result["sort"]
                circle.validation_status = "verified"
                circle.validation_error = None
                circle.validated_at = completed_at
                if first_validation:
                    circle.first_validated_at = completed_at
                    if circle.source_kind == "configured":
                        circle.auto_enabled = True
                circle.adapter_version = result["adapter_version"]
        self._publish_validation(circle_id, job_id, "success")
        return True

    def _publish_validation(self, circle_id: str, job_id: str, status: str) -> None:
        if self.event_publisher:
            self.event_publisher("validation.changed", circle_id, job_id=job_id, status=status)

    def _process_platform_head(self, platform_code: str) -> bool:
        if self._official_reputation_waiting(platform_code):
            return False
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
            running_summary_version = run.summary_version
            running_completed_count = run.completed_count
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
        if self.event_publisher:
            self.event_publisher(
                "run.changed",
                run_id,
                summary_version=running_summary_version,
                status="running",
                completed_count=running_completed_count,
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
            screenshot_task_ids: list[str] = []
            for task_id, result in results.items():
                task = db.get(CircleTask, task_id)
                if task:
                    self._apply_result(db, task, result)
                    if bool((task.config_snapshot or {}).get("screenshot_enabled", True)):
                        screenshot_task_ids.append(task_id)
            aggregate_run(db, run)
            summary_version = run.summary_version
            status = run.status
        if self.screenshot_service:
            for task_id in screenshot_task_ids:
                self.screenshot_service.mark_task_complete(task_id)
        if self.event_publisher:
            self.event_publisher(
                "run.changed", run_id, summary_version=summary_version, status=status
            )
        return True

    def _official_reputation_waiting(self, platform_code: str | None = None) -> bool:
        """正式口碑批次排队或运行时，普通平台任务停止领取新工作。"""

        with self.factory() as db:
            rows = db.scalars(
                select(ReputationRun).where(
                    ReputationRun.source_type == "scheduled",
                    ReputationRun.status.in_(["queued", "running"]),
                )
            ).all()
            return any(
                platform_code is None or platform_code in (row.platform_codes or []) for row in rows
            )

    def _execute_task(self, collector: Collector, task_id: str) -> dict[str, Any]:
        with self.factory() as db:
            task = db.get(CircleTask, task_id)
            assert task is not None
            snapshot = dict(task.config_snapshot or {})
            circle_url = task.circle_url
            target = task.target_count
            transient = bool(snapshot.get("transient"))
            circle_id = task.circle_id
            known_urls = list(snapshot.get("known_post_urls") or [])
            source_indexes = dict(snapshot.get("source_indexes") or {})
            screenshot_enabled = bool(snapshot.get("screenshot_enabled", True))
            persisted_post_ids = set(
                db.scalars(
                    select(PostSnapshot.platform_post_id).where(
                        PostSnapshot.circle_task_id == task_id
                    )
                )
            )
            completed_post_ids = set(persisted_post_ids)
            completed_post_ids.update(
                post_id
                for post_id in snapshot.get("skip_post_ids", [])
                if isinstance(post_id, str) and post_id
            )
            needs_validation = transient
            platform_code = task.platform_code
            spec = get_platform_spec(platform_code)
            page_evidence_supported = _supports_page_evidence(collector)
            if circle_id:
                circle = db.get(Circle, circle_id)
                needs_validation = bool(circle and circle.validation_status != "verified")
        if (
            self.screenshot_service
            and screenshot_enabled
            and not known_urls
            and page_evidence_supported
        ):
            self.screenshot_service.register_task(task_id)
        pending_records: list[dict[str, Any]] = []
        reported_failures = 0
        flushed_failures = 0
        progress_batch_size = 1 if target <= 20 else 10
        def flush_progress() -> None:
            nonlocal pending_records, flushed_failures
            if not pending_records and reported_failures == flushed_failures:
                return
            self._apply_progress(task_id, pending_records, reported_failures)
            pending_records = []
            flushed_failures = reported_failures

        def report_progress(
            record: dict[str, Any] | None, failure: dict[str, Any] | None
        ) -> None:
            nonlocal reported_failures
            if record is not None:
                raw_status = record.get("raw_status") or {}
                resolver = getattr(collector, "resolve_video_urls", None)
                if (
                    spec.supports_live_video_resolution
                    and resolver is not None
                    and not record.get("video_urls")
                    and raw_status.get("video_id")
                ):
                    try:
                        record["video_urls"] = resolver(str(raw_status["video_id"]))
                        raw_status["video_url_resolution"] = (
                            "resolved" if record["video_urls"] else "not_found"
                        )
                    except Exception as exc:
                        raw_status["video_url_resolution"] = "failed"
                        raw_status["video_url_resolution_error"] = type(exc).__name__
                    record["raw_status"] = raw_status
                if source_indexes:
                    record["order_index"] = int(
                        source_indexes.get(record.get("url"), record.get("order_index", 0))
                    )
                pending_records.append(record)
            if failure is not None:
                reported_failures += 1
            if (
                len(pending_records) + reported_failures - flushed_failures
                >= progress_batch_size
            ):
                flush_progress()

        validation = None
        generation = self.refresh_generation.get(platform_code, 0)
        try:
            if needs_validation:
                validation = collector.validate_circle(circle_url)
            remaining = max(0, target - len(persisted_post_ids))
            payload = (
                collector.collect_urls(known_urls, on_progress=report_progress)
                if known_urls
                else collector.collect_circle(
                    circle_url,
                    remaining,
                    skip_post_ids=completed_post_ids,
                    on_progress=report_progress,
                    **(
                        {
                            "on_page_evidence": self.screenshot_service.capture_callback(task_id)
                        }
                        if self.screenshot_service
                        and screenshot_enabled
                        and page_evidence_supported
                        else {}
                    ),
                )
            )
            if source_indexes:
                for record in payload.get("records") or []:
                    record["order_index"] = int(
                        source_indexes.get(record.get("url"), record.get("order_index", 0))
                    )
                for failure in payload.get("failures") or []:
                    failure["source_index"] = int(
                        source_indexes.get(failure.get("url"), failure.get("source_index", 0))
                    )
            return {"kind": "done", "validation": validation, **payload}
        except AuthenticationRequired as exc:
            trigger_url = exc.trigger_url or circle_url
            if self._refresh_after_auth(platform_code, trigger_url, generation):
                with self.factory() as db:
                    platform = db.get(PlatformConfig, platform_code)
                    assert platform is not None
                    refreshed = self._collector(platform, collector.concurrency)
                    refreshed_page_evidence_supported = _supports_page_evidence(refreshed)
                try:
                    if needs_validation and validation is None:
                        validation = refreshed.validate_circle(circle_url)
                    payload = (
                        refreshed.collect_urls(known_urls, on_progress=report_progress)
                        if known_urls
                        else refreshed.collect_circle(
                            circle_url,
                            remaining,
                            skip_post_ids=completed_post_ids,
                            on_progress=report_progress,
                            **(
                                {
                                    "on_page_evidence": self.screenshot_service.capture_callback(
                                        task_id
                                    )
                                }
                                if self.screenshot_service
                                and screenshot_enabled
                                and refreshed_page_evidence_supported
                                else {}
                            ),
                        )
                    )
                    if source_indexes:
                        for record in payload.get("records") or []:
                            record["order_index"] = int(
                                source_indexes.get(record.get("url"), record.get("order_index", 0))
                            )
                        for failure in payload.get("failures") or []:
                            failure["source_index"] = int(
                                source_indexes.get(
                                    failure.get("url"), failure.get("source_index", 0)
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
        finally:
            flush_progress()

    def _refresh_after_auth(
        self, platform_code: str, trigger_url: str, observed_generation: int
    ) -> bool:
        """同一认证失效事件只允许一个线程刷新服务器 Session。"""

        with self.refresh_lock:
            spec = get_platform_spec(platform_code)
            if not spec.supports_authentication:
                return False
            if self.refresh_generation.get(platform_code, 0) > observed_generation:
                return True
            state = self.session_store.get_state(platform_code)
            if not state:
                return False
            try:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(
                        headless=self.session_store.settings.auth_browser_headless,
                        args=browser_launch_args(),
                    )
                    context = browser.new_context(
                        storage_state=state,
                        locale="zh-CN",
                        timezone_id=self.session_store.settings.timezone,
                    )
                    page = context.new_page()
                    page.goto(
                        trigger_url or spec.login_url or spec.auth_probe_circle_url or "about:blank",
                        wait_until="domcontentloaded",
                        timeout=60_000,
                    )
                    page.wait_for_timeout(1000)
                    if any(marker in page.url for marker in spec.auth_url_markers):
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
                        Circle.section == task.section,
                        Circle.list_order == task.list_order,
                    )
                )
            if not circle:
                circle = Circle(
                    platform_code=task.platform_code,
                    external_id=task.external_id,
                    url=validation["url"],
                    section=task.section,
                    list_order=task.list_order,
                    source_kind="manual_history",
                )
                db.add(circle)
                db.flush()
                task.circle_id = circle.id
            completed_at = utc_now()
            circle.name = validation["name"]
            circle.url = validation["url"]
            circle.list_order = validation["sort"]
            circle.validation_status = "verified"
            circle.validation_error = None
            if circle.first_validated_at is None:
                circle.first_validated_at = completed_at
            circle.validated_at = completed_at
            circle.adapter_version = validation["adapter_version"]
            circle.last_used_at = utc_now()
            task.circle_name = validation["name"]
            task.circle_url = validation["url"]
            task.list_order = validation["sort"]
        records = result.get("records") or []
        failures = result.get("failures") or []
        existing = self._store_records(db, task, records)
        task.completed_count = len(existing)
        task.checkpoint = {
            "trigger_url": result.get("trigger_url"),
            "failed_urls": failures,
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
        # 候选请求错误可能已由后续候选补足，只在最终仍未完成的任务中计为失败。
        # 成功任务与等待认证任务的业务失败数保持为零，原始诊断仍保存在检查点。
        task.failed_count = (
            len(failures) if task.status in {"partial_success", "failed"} else 0
        )

    def _apply_progress(
        self, task_id: str, records: list[dict[str, Any]], _candidate_failure_count: int
    ) -> None:
        """分段提交已完成快照，并在事务完成后通知前端回查权威进度。"""

        with self.factory.begin() as db:
            task = db.get(CircleTask, task_id)
            if not task or task.status != "running":
                return
            existing = self._store_records(db, task, records)
            task.completed_count = len(existing)
            # 运行中的候选错误还可能被后续候选补足，不提前写入最终失败计数。
            # 调用方仍以候选错误触发分段提交；终态由 _apply_result 统一判定并落库。
            task.failed_count = 0
            checkpoint = dict(task.checkpoint or {})
            checkpoint["completed_post_ids"] = sorted(existing)
            task.checkpoint = checkpoint
            run = db.get(ExtractionRun, task.run_id)
            if not run:
                return
            aggregate_run(db, run)
            run_id = run.id
            summary_version = run.summary_version
            completed_count = run.completed_count
            current_status = run.status
        if self.event_publisher:
            self.event_publisher(
                "run.changed",
                run_id,
                summary_version=summary_version,
                status=current_status,
                completed_count=completed_count,
            )

    def _store_records(
        self,
        db: Session, task: CircleTask, records: list[dict[str, Any]]
    ) -> set[str]:
        """按任务幂等保存一组帖子和主评论，并返回当前全部帖子 ID。"""

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
                order_index=int(record.get("order_index", next_order)),
            )
            db.add(post)
            db.flush()
            screenshot_enabled = bool((task.config_snapshot or {}).get("screenshot_enabled", True))
            if self.screenshot_service and screenshot_enabled:
                self.screenshot_service.link_post(db, task.id, post)
            if self.sentiment_service:
                self.sentiment_service.enqueue_for_post(
                    db,
                    post,
                    task.platform_code,
                    analysis_enabled=bool(
                        (task.config_snapshot or {}).get("ai_analysis_enabled", True)
                    ),
                )
            next_order = max(next_order + 1, int(record.get("order_index", next_order)) + 1)
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
        return existing

    def resume_platform(self, platform_code: str) -> None:
        """认证状态更新后先恢复原等待任务和验证任务。"""

        resumed_runs: dict[str, tuple[int, int]] = {}
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
                    resumed_runs[run.id] = (run.summary_version, run.completed_count)
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
        if self.event_publisher:
            for run_id, (summary_version, completed_count) in resumed_runs.items():
                self.event_publisher(
                    "run.changed",
                    run_id,
                    summary_version=summary_version,
                    status="queued",
                    completed_count=completed_count,
                )


_SIGNED_VIDEO_EXPIRY = re.compile(r"/([0-9a-fA-F]{8})/video/")


def playback_url_expiry(url: str) -> datetime | None:
    """读取已观察到的懂车帝 CDN 路径到期时间；未知格式返回空。"""

    match = _SIGNED_VIDEO_EXPIRY.search(urlsplit(url).path)
    if not match:
        return None
    try:
        value = datetime.fromtimestamp(int(match.group(1), 16), timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None
    return value if 2020 <= value.year <= 2100 else None
