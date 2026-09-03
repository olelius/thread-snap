"""持久平台 FIFO、圈子验证和提取 Worker。"""

from __future__ import annotations

import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
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

NETWORK_RETRYABLE_FAILURE_CODE = "PLATFORM_NETWORK_ERROR"
RATE_LIMIT_RETRYABLE_FAILURE_CODE = "PLATFORM_RATE_LIMITED"
RETRYABLE_ACCESS_FAILURE_CODES = {
    NETWORK_RETRYABLE_FAILURE_CODE,
    RATE_LIMIT_RETRYABLE_FAILURE_CODE,
}
# 页面证据列表偶发未触发时，等同一批次首轮来源全部完成后统一复访一次。
BATCH_RETRYABLE_SOURCE_FAILURE_CODES = {"PAGE_EVIDENCE_LIST_RESPONSE_MISSING"}
BATCH_RETRY_WAVE_KEY = "batch_retry_wave"
INTERACTIVE_RECOVERY_CODES = {"PLATFORM_CAPTCHA_REQUIRED", "PLATFORM_CHALLENGE"}
AUTH_RECOVERY_PROBE_KEY = "auth_recovery_probe"
AUTH_RECOVERY_BLOCKED_KEY = "auth_recovery_blocked"
RETRY_BASE_SECONDS = 2
RETRY_MAX_SECONDS = 60
RATE_LIMIT_RETRY_BASE_SECONDS = 60
RATE_LIMIT_RETRY_MAX_SECONDS = 900
YICHE_RATE_LIMIT_PROBE_SECONDS = 10


def _retry_delay_seconds(error_code: str, attempt: int, *, platform_code: str | None = None) -> int:
    """按失败类别和平台返回持久恢复等待时间。"""

    normalized_attempt = max(1, attempt)
    if error_code == RATE_LIMIT_RETRYABLE_FAILURE_CODE:
        if platform_code == "yiche":
            return YICHE_RATE_LIMIT_PROBE_SECONDS
        return min(
            RATE_LIMIT_RETRY_MAX_SECONDS,
            RATE_LIMIT_RETRY_BASE_SECONDS * 2 ** (normalized_attempt - 1),
        )
    return min(RETRY_MAX_SECONDS, RETRY_BASE_SECONDS * 2 ** (normalized_attempt - 1))


def _supports_page_evidence(collector: Collector) -> bool:
    """同时核对能力声明与调用签名，避免把截图回调传给旧适配器。"""

    return bool(getattr(collector, "supports_page_evidence", False)) and (
        "on_page_evidence" in signature(collector.collect_circle).parameters
    )


def _retry_due(task: CircleTask, now: datetime) -> bool:
    """判断持久重试任务是否已到下一次固定候选访问时间。"""

    value = str((task.checkpoint or {}).get("retry_not_before") or "")
    if not value:
        return True
    try:
        not_before = datetime.fromisoformat(value)
    except ValueError:
        return True
    if not_before.tzinfo is None:
        not_before = not_before.replace(tzinfo=timezone.utc)
    return not_before <= now


def _is_batch_retry_task(task: CircleTask) -> bool:
    """识别等待批次首轮收尾后再复访的来源任务。"""

    return bool((task.checkpoint or {}).get(BATCH_RETRY_WAVE_KEY))


class WorkerService:
    """一个协调线程通过独立平台通道驱动持久 FIFO 任务。"""

    def __init__(
        self,
        factory: sessionmaker[Session],
        session_store: SessionStore,
        poll_seconds: float = 1.0,
        platform_level_concurrency: int = 3,
        event_publisher: Callable[..., Any] | None = None,
        sentiment_service: SentimentService | None = None,
        screenshot_service: ScreenshotService | None = None,
    ):
        self.factory = factory
        self.session_store = session_store
        self.poll_seconds = poll_seconds
        self.platform_level_concurrency = min(max(int(platform_level_concurrency), 1), 3)
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
        if platform_codes:
            # 每个平台各自领取本平台 FIFO 队首；平台之间并行，平台内部仍由
            # _process_platform_head 使用任务快照中的总并发控制。Collector 在
            # 通道内创建，避免在线程之间共享平台 Session 或浏览器上下文。
            with ThreadPoolExecutor(
                max_workers=min(self.platform_level_concurrency, len(platform_codes))
            ) as pool:
                futures = [pool.submit(self._process_platform_head, code) for code in platform_codes]
                results = [future.result() for future in futures]
                if any(results):
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
        collector = None
        try:
            with self.factory() as db:
                platform = db.get(PlatformConfig, platform_code)
                assert platform is not None
                collector = self._collector(platform)
                result = collector.validate_circle(circle_url)
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
        finally:
            close = getattr(collector, "close", None)
            if callable(close):
                close()
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
            platform_queued = list(
                db.scalars(
                    select(CircleTask)
                    .where(
                        CircleTask.platform_code == platform_code,
                        CircleTask.status == "queued",
                    )
                    .order_by(CircleTask.queue_sequence)
                )
            )
            if not platform_queued:
                return False
            head = platform_queued[0]
            if _is_batch_retry_task(head):
                run_tasks = list(
                    db.scalars(
                        select(CircleTask).where(CircleTask.run_id == head.run_id)
                    )
                )
                first_wave_pending = any(
                    task.status in {"queued", "running"} and not _is_batch_retry_task(task)
                    for task in run_tasks
                )
                if first_wave_pending:
                    # 同批次同平台后续首轮来源先完成；其他平台仍可并行推进。
                    head = next(
                        (
                            task
                            for task in platform_queued
                            if task.run_id == head.run_id and not _is_batch_retry_task(task)
                        ),
                        None,
                    )
                    if head is None:
                        return False
            run = db.get(ExtractionRun, head.run_id)
            platform = db.get(PlatformConfig, platform_code)
            if not run or not platform:
                return False
            queued_tasks = list(
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
            run_tasks = list(db.scalars(select(CircleTask).where(CircleTask.run_id == run.id)))
            first_wave_pending = any(
                task.status in {"queued", "running"} and not _is_batch_retry_task(task)
                for task in run_tasks
            )
            if first_wave_pending:
                queued_tasks = [task for task in queued_tasks if not _is_batch_retry_task(task)]
                if not queued_tasks:
                    return False
            now = utc_now()
            auth_probe_tasks = [
                task
                for task in queued_tasks
                if bool((task.checkpoint or {}).get(AUTH_RECOVERY_PROBE_KEY))
            ]
            blocked_recovery_tasks = [
                task
                for task in queued_tasks
                if bool((task.checkpoint or {}).get(AUTH_RECOVERY_BLOCKED_KEY))
            ]
            auth_recovery_probe = False
            if auth_probe_tasks:
                probe = min(auth_probe_tasks, key=lambda item: item.queue_sequence)
                if not _retry_due(probe, now):
                    return False
                tasks = [probe]
                auth_recovery_probe = True
            elif blocked_recovery_tasks:
                # 进程若恰在认证恢复标记落库后中断，自动提升最早的阻塞任务，
                # 避免残留检查点让平台队列永久停住。
                probe = min(blocked_recovery_tasks, key=lambda item: item.queue_sequence)
                checkpoint = dict(probe.checkpoint or {})
                checkpoint.pop(AUTH_RECOVERY_BLOCKED_KEY, None)
                checkpoint[AUTH_RECOVERY_PROBE_KEY] = True
                probe.checkpoint = checkpoint
                if not _retry_due(probe, now):
                    return False
                tasks = [probe]
                auth_recovery_probe = True
            else:
                if not _retry_due(head, now):
                    return False
                tasks = [task for task in queued_tasks if _retry_due(task, now)]
            rate_limited_tasks = [
                task
                for task in tasks
                if (task.checkpoint or {}).get("retry_error_code")
                == RATE_LIMIT_RETRYABLE_FAILURE_CODE
            ]
            rate_limit_recovery = False
            if rate_limited_tasks and not auth_recovery_probe:
                first_rate_limited = min(rate_limited_tasks, key=lambda item: item.queue_sequence)
                tasks_before_rate_limit = [
                    task
                    for task in tasks
                    if task.queue_sequence < first_rate_limited.queue_sequence
                ]
                if tasks_before_rate_limit:
                    tasks = tasks_before_rate_limit
                else:
                    # 平台已经明确限流时只复访一个队首来源，并把实际请求并发收敛为1；
                    # 成功后下一来源再按FIFO领取，避免冷却结束瞬间重新形成请求突发。
                    tasks = [first_rate_limited]
                    rate_limit_recovery = True
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
            if rate_limit_recovery or auth_recovery_probe:
                concurrency = 1
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
        try:
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
        finally:
            close = getattr(collector, "close", None)
            if callable(close):
                close()
        with self.factory.begin() as db:
            run = db.get(ExtractionRun, run_id)
            assert run is not None
            screenshot_task_ids: list[str] = []
            for task_id, result in results.items():
                task = db.get(CircleTask, task_id)
                if task:
                    self._apply_result(db, task, result)
                    self._release_auth_recovery(db, task)
                    if task.status in {"success", "partial_success", "failed"} and bool(
                        (task.config_snapshot or {}).get("screenshot_enabled", True)
                    ):
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
            checkpoint = dict(task.checkpoint or {})
            circle_url = task.circle_url
            target = task.target_count
            transient = bool(snapshot.get("transient"))
            circle_id = task.circle_id
            configured_known_urls = list(snapshot.get("known_post_urls") or [])
            known_url_task = bool(configured_known_urls)
            known_urls = list(configured_known_urls)
            source_indexes = dict(snapshot.get("source_indexes") or {})
            if configured_known_urls and not source_indexes:
                source_indexes = {
                    str(url): index for index, url in enumerate(configured_known_urls)
                }
            retry_urls = [
                str(value)
                for value in checkpoint.get("retry_urls") or []
                if isinstance(value, str) and value
            ]
            if retry_urls:
                known_url_task = True
                known_urls = retry_urls
                source_indexes = {
                    str(key): int(value)
                    for key, value in dict(checkpoint.get("retry_source_indexes") or {}).items()
                }
            prior_terminal_failures = list(checkpoint.get("terminal_failures") or [])
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
            if known_urls and persisted_post_ids and spec.normalize_post_url is not None:
                unresolved_urls: list[str] = []
                for url in known_urls:
                    try:
                        post_id, _ = spec.normalize_post_url(url)
                    except CollectorFailure:
                        unresolved_urls.append(url)
                        continue
                    if post_id not in persisted_post_ids:
                        unresolved_urls.append(url)
                known_urls = unresolved_urls
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

        def finalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
            """把固定候选的瞬时网络错误转为原任务持久重试。"""

            current_failures = list(payload.get("failures") or [])
            retryable = [
                failure
                for failure in current_failures
                if failure.get("code") in RETRYABLE_ACCESS_FAILURE_CODES
            ]
            retry_error_code = next(
                (
                    RATE_LIMIT_RETRYABLE_FAILURE_CODE
                    for failure in retryable
                    if failure.get("code") == RATE_LIMIT_RETRYABLE_FAILURE_CODE
                ),
                NETWORK_RETRYABLE_FAILURE_CODE if retryable else None,
            )
            terminal = prior_terminal_failures + [
                failure
                for failure in current_failures
                if failure.get("code") not in RETRYABLE_ACCESS_FAILURE_CODES
            ]
            payload["failures"] = terminal + retryable
            return {
                "kind": "retry" if retryable else "done",
                "validation": validation,
                "retry_failures": retryable,
                "retry_error_code": retry_error_code,
                "terminal_failures": terminal,
                **payload,
            }

        def collector_failure_result(exc: CollectorFailure) -> dict[str, Any]:
            """统一分类首次请求和会话刷新后的平台控制错误。"""

            if exc.code in INTERACTIVE_RECOVERY_CODES:
                return {
                    "kind": "auth",
                    "code": exc.code,
                    "message": exc.message,
                    "trigger_url": exc.trigger_url or circle_url,
                    "records": [],
                    "failures": prior_terminal_failures,
                    "validation": validation,
                    "retry_urls": retry_urls,
                    "retry_source_indexes": source_indexes,
                    "terminal_failures": prior_terminal_failures,
                }
            if exc.code in RETRYABLE_ACCESS_FAILURE_CODES:
                failure = {
                    "url": exc.trigger_url or circle_url,
                    "code": exc.code,
                    "message": exc.message,
                    "source_index": 0,
                }
                return {
                    "kind": "retry",
                    "records": [],
                    "failures": prior_terminal_failures + [failure],
                    "retry_failures": [failure],
                    "retry_error_code": exc.code,
                    "terminal_failures": prior_terminal_failures,
                    "retry_scope": "source",
                    "validation": validation,
                }
            if exc.code in BATCH_RETRYABLE_SOURCE_FAILURE_CODES:
                previous_batch_retry = bool((checkpoint or {}).get(BATCH_RETRY_WAVE_KEY))
                if previous_batch_retry:
                    return {
                        "kind": "failed",
                        "code": exc.code,
                        "message": exc.message,
                        "records": [],
                        "failures": [],
                        "validation": validation,
                    }
                failure = {
                    "url": exc.trigger_url or circle_url,
                    "code": exc.code,
                    "message": exc.message,
                    "source_index": 0,
                }
                return {
                    "kind": "retry",
                    "records": [],
                    "failures": [failure],
                    "retry_failures": [failure],
                    "retry_error_code": exc.code,
                    "terminal_failures": prior_terminal_failures,
                    "retry_scope": "source",
                    "retry_wave": "batch",
                    "validation": validation,
                }
            return {
                "kind": "failed",
                "code": exc.code,
                "message": exc.message,
                "records": [],
                "failures": [],
                "validation": validation,
            }

        try:
            if needs_validation:
                validation = collector.validate_circle(circle_url)
            remaining = max(0, target - len(persisted_post_ids))
            payload = (
                collector.collect_urls(known_urls, on_progress=report_progress)
                if known_urls
                else {
                    "records": [],
                    "failures": [],
                    "stop_reason": "URL 清单中没有尚未完成的帖子。",
                }
                if known_url_task
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
            return finalize_payload(payload)
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
                        else {
                            "records": [],
                            "failures": [],
                            "stop_reason": "URL 清单中没有尚未完成的帖子。",
                        }
                        if known_url_task
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
                    return finalize_payload(payload)
                except AuthenticationRequired as repeated:
                    exc = repeated
                except CollectorFailure as repeated_control:
                    return collector_failure_result(repeated_control)
                finally:
                    close = getattr(refreshed, "close", None)
                    if callable(close):
                        close()
            return {
                "kind": "auth",
                "code": "AUTH_REQUIRED",
                "message": exc.message,
                "trigger_url": exc.trigger_url or trigger_url,
                "records": exc.records,
                "failures": exc.failures,
                "validation": validation,
                "retry_urls": retry_urls,
                "retry_source_indexes": source_indexes,
                "terminal_failures": prior_terminal_failures,
            }
        except CollectorFailure as exc:
            return collector_failure_result(exc)
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
        previous_checkpoint = dict(task.checkpoint or {})
        checkpoint = {
            "trigger_url": result.get("trigger_url"),
            "failed_urls": failures,
            "completed_post_ids": sorted(existing),
        }
        for recovery_key in (AUTH_RECOVERY_PROBE_KEY, AUTH_RECOVERY_BLOCKED_KEY):
            if recovery_key in previous_checkpoint:
                checkpoint[recovery_key] = bool(previous_checkpoint[recovery_key])
        if result["kind"] == "retry":
            retry_failures = list(result.get("retry_failures") or [])
            retry_error_code = str(
                result.get("retry_error_code")
                or next(
                    (
                        failure.get("code")
                        for failure in retry_failures
                        if failure.get("code")
                        in RETRYABLE_ACCESS_FAILURE_CODES | BATCH_RETRYABLE_SOURCE_FAILURE_CODES
                    ),
                    NETWORK_RETRYABLE_FAILURE_CODE,
                )
            )
            previous_retry_attempt = int(previous_checkpoint.get("retry_attempt") or 0)
            previous_limit_completed_value = previous_checkpoint.get(
                "rate_limit_completed_count"
            )
            previous_limit_completed = (
                task.completed_count
                if previous_limit_completed_value is None
                else int(previous_limit_completed_value)
            )
            made_progress_since_limit = (
                retry_error_code == RATE_LIMIT_RETRYABLE_FAILURE_CODE
                and task.completed_count > previous_limit_completed
            )
            retry_attempt = 1 if made_progress_since_limit else previous_retry_attempt + 1
            delay_seconds = _retry_delay_seconds(
                retry_error_code,
                retry_attempt,
                platform_code=task.platform_code,
            )
            retry_scope = str(result.get("retry_scope") or "candidate")
            retry_urls = (
                []
                if retry_scope == "source"
                else [str(failure["url"]) for failure in retry_failures]
            )
            checkpoint.update(
                {
                    "retry_urls": retry_urls,
                    "retry_source_indexes": {
                        str(failure["url"]): int(failure.get("source_index") or 0)
                        for failure in retry_failures
                    },
                    "terminal_failures": list(result.get("terminal_failures") or []),
                    "retry_attempt": retry_attempt,
                    "retry_error_code": retry_error_code,
                    "retry_not_before": (utc_now() + timedelta(seconds=delay_seconds)).isoformat(),
                    "retry_scope": retry_scope,
                }
            )
            if retry_error_code in BATCH_RETRYABLE_SOURCE_FAILURE_CODES:
                checkpoint[BATCH_RETRY_WAVE_KEY] = True
            if retry_error_code == RATE_LIMIT_RETRYABLE_FAILURE_CODE:
                checkpoint["rate_limit_completed_count"] = task.completed_count
        elif result["kind"] == "auth" and result.get("retry_urls"):
            checkpoint.update(
                {
                    "retry_urls": list(result.get("retry_urls") or []),
                    "retry_source_indexes": dict(result.get("retry_source_indexes") or {}),
                    "terminal_failures": list(result.get("terminal_failures") or []),
                    "retry_attempt": int((task.checkpoint or {}).get("retry_attempt") or 0),
                }
            )
        task.checkpoint = checkpoint
        if result["kind"] == "auth":
            task.status = "waiting_for_auth"
            task.error_code = result["code"]
            task.error_message = result["message"]
            task.stop_reason = None
        elif result["kind"] == "retry":
            task.status = "queued"
            task.error_code = None
            task.error_message = None
            if checkpoint.get("retry_error_code") == RATE_LIMIT_RETRYABLE_FAILURE_CODE:
                task.stop_reason = (
                    "易车请求频率受限，10秒后以单来源单并发探针自动续跑原任务。"
                    if task.platform_code == "yiche"
                    else "平台请求频率受限，正在冷却并自动续跑原任务。"
                )
            elif checkpoint.get(BATCH_RETRY_WAVE_KEY):
                task.stop_reason = "首轮批次完成后统一复访来源。"
            else:
                task.stop_reason = "固定访问暂时失败，正在自动重试原 URL。"
            task.finished_at = None
        elif result["kind"] == "failed":
            task.status = "partial_success" if task.completed_count else "failed"
            task.error_code = result["code"]
            task.error_message = result["message"]
            task.stop_reason = result["message"]
            task.finished_at = utc_now()
        else:
            task.stop_reason = result.get("stop_reason")
            shortage_by_error = bool(result.get("failures"))
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

    def _release_auth_recovery(self, db: Session, task: CircleTask) -> None:
        """认证探针形成终态后释放同批次其余来源，下一轮恢复冻结并发。"""

        checkpoint = dict(task.checkpoint or {})
        if not checkpoint.get(AUTH_RECOVERY_PROBE_KEY):
            return
        if task.status not in {"success", "partial_success", "failed"}:
            return
        checkpoint.pop(AUTH_RECOVERY_PROBE_KEY, None)
        checkpoint.pop(AUTH_RECOVERY_BLOCKED_KEY, None)
        task.checkpoint = checkpoint
        siblings = db.scalars(
            select(CircleTask).where(
                CircleTask.run_id == task.run_id,
                CircleTask.platform_code == task.platform_code,
                CircleTask.status == "queued",
                CircleTask.id != task.id,
            )
        )
        for sibling in siblings:
            sibling_checkpoint = dict(sibling.checkpoint or {})
            sibling_checkpoint.pop(AUTH_RECOVERY_BLOCKED_KEY, None)
            sibling.checkpoint = sibling_checkpoint

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
            # 运行中的访问错误尚未完成“自动重试或终态错误”分类，不提前写入失败数。
            # 调用方仍以候选错误触发分段提交；分类与终态由 _apply_result 统一落库。
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
            waiting_tasks = list(
                db.scalars(
                    select(CircleTask)
                    .where(
                    CircleTask.platform_code == platform_code,
                    CircleTask.status == "waiting_for_auth",
                )
                    .order_by(CircleTask.queue_sequence)
                )
            )
            waiting_by_run: dict[str, list[CircleTask]] = {}
            for task in waiting_tasks:
                waiting_by_run.setdefault(task.run_id, []).append(task)
                task.status = "queued"
                task.error_code = None
                task.error_message = None
                run = db.get(ExtractionRun, task.run_id)
                if run:
                    run.status = "queued"
                    run.waiting_reason = None
                    resumed_runs[run.id] = (run.summary_version, run.completed_count)
            # 当前 session 关闭了查询前自动 flush；先让状态切换进入事务视图，
            # 后续才能同时取得刚恢复的任务与原本已排队的同批次来源。
            db.flush()
            for run_id, resumed_tasks in waiting_by_run.items():
                probe = min(resumed_tasks, key=lambda item: item.queue_sequence)
                pending_tasks = list(
                    db.scalars(
                        select(CircleTask).where(
                            CircleTask.run_id == run_id,
                            CircleTask.platform_code == platform_code,
                            CircleTask.status == "queued",
                        )
                    )
                )
                for task in pending_tasks:
                    checkpoint = dict(task.checkpoint or {})
                    checkpoint.pop(AUTH_RECOVERY_PROBE_KEY, None)
                    checkpoint.pop(AUTH_RECOVERY_BLOCKED_KEY, None)
                    if task.id == probe.id:
                        checkpoint[AUTH_RECOVERY_PROBE_KEY] = True
                    else:
                        checkpoint[AUTH_RECOVERY_BLOCKED_KEY] = True
                    task.checkpoint = checkpoint
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
