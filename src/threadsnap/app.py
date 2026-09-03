"""FastAPI 应用工厂与双接口控制器。"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime
from ipaddress import ip_address
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    Query,
    Request,
    UploadFile,
    WebSocket,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from sqlalchemy.exc import OperationalError

from .auth import BrowserAuthManager
from .config import Settings, get_settings
from .db import build_engine, build_session_factory, migrate_database
from .errors import DomainError, domain_error_handler
from .events import EventBus
from .ids import uuid7
from .local_sentiment import LocalSentimentAnalyzer
from .models import ValidationJob
from .reputation import (
    MappingPasteRequest,
    MappingValidationRequest,
    ReputationService,
    ScopePublishRequest,
    ScopeVehicleCreateRequest,
    ScopeVehicleRevisionRequest,
    ScopeVehicleUpdateRequest,
    SyntheticRunCreate,
)
from .reputation_scheduler import ReputationCoordinator
from .scheduler import SchedulerService
from .schemas import (
    CircleBatchUpdate,
    CircleRow,
    ExportCreate,
    ExtractionPlanUpdate,
    ManualRunCreate,
    ManualSentimentRevisionCreate,
    PlatformConfigUpdate,
    SentimentConfigUpdate,
    SessionImport,
)
from .screenshots import ScreenshotService
from .sentiment import SentimentService, SentimentWorker
from .services import ConfigService, RunService, bootstrap_database, validation_job_dict
from .session_store import SessionStore
from .templates import TemplateService
from .worker import WorkerService


class Container:
    """应用服务容器，便于测试替换数据库和后台线程。"""

    def __init__(self, settings: Settings):
        settings.ensure_directories()
        self.settings = settings
        migrate_database(settings.database_url)
        self.engine = build_engine(settings.database_url)
        self.sessions = build_session_factory(self.engine)
        with self.sessions.begin() as db:
            bootstrap_database(db)
        self.session_store = SessionStore(settings, self.sessions)
        yiche_state = self.session_store.get_state("yiche")
        if yiche_state and not any(
            isinstance(item, dict)
            and item.get("name") == "username"
            and isinstance(item.get("value"), str)
            and bool(item["value"])
            for item in yiche_state.get("cookies", [])
        ):
            self.session_store.mark_invalid(
                "yiche", "历史访问会话不包含易车账号身份，请重新完成登录认证。"
            )
        if (
            settings.dongchedi_storage_state
            and settings.dongchedi_storage_state.is_file()
            and not self.session_store.get_state("dongchedi")
        ):
            self.session_store.import_file("dongchedi", settings.dongchedi_storage_state)
        self.config = ConfigService(self.sessions)
        self.runs = RunService(self.sessions, settings.timezone)
        self.events = EventBus()
        self.reputation = ReputationService(
            self.sessions,
            settings,
            session_store=self.session_store,
            event_publisher=self.events.publish,
        )
        self.reputation_coordinator = ReputationCoordinator(
            self.reputation, settings.scheduler_poll_seconds
        )
        self.local_sentiment = LocalSentimentAnalyzer(
            settings.paddlenlp_home,
            num_threads=settings.local_sentiment_num_threads,
        )
        self.sentiment = SentimentService(
            self.sessions,
            self.session_store,
            event_publisher=self.events.publish,
            local_analyzer=self.local_sentiment,
        )
        self.screenshots = ScreenshotService(self.sessions, settings)
        self.worker = WorkerService(
            self.sessions,
            self.session_store,
            settings.worker_poll_seconds,
            platform_level_concurrency=settings.platform_level_concurrency,
            event_publisher=self.events.publish,
            sentiment_service=self.sentiment,
            screenshot_service=self.screenshots,
        )
        self.sentiment_worker = SentimentWorker(
            self.sentiment,
            settings.worker_poll_seconds,
            media_resolver=self.worker.resolve_post_video_urls,
        )
        self.scheduler = SchedulerService(
            self.sessions,
            self.runs,
            settings.scheduler_poll_seconds,
            event_publisher=self.events.publish,
        )
        self.templates = TemplateService(self.sessions, settings)
        self.auth = BrowserAuthManager(
            settings,
            self.session_store,
            self.worker,
            event_publisher=self.events.publish,
        )

    async def start(self) -> None:
        if self.settings.start_background_services:
            self.worker.start()
            self.sentiment_worker.start()
            self.scheduler.start()
            self.reputation_coordinator.start()

    async def stop(self) -> None:
        self.reputation_coordinator.stop()
        self.scheduler.stop()
        self.sentiment_worker.stop()
        self.worker.stop()
        self.sentiment.close()
        self.local_sentiment.close()
        await self.auth.close_all()
        self.engine.dispose()


def _container(request: Request) -> Container:
    return request.app.state.container


def require_internal_loopback(request: Request) -> None:
    """集成接口只接受本机进程访问，对外前端只使用页面 API。"""

    host = request.client.host if request.client else ""
    if host == "testclient":
        return
    try:
        allowed = ip_address(host).is_loopback
    except ValueError:
        allowed = False
    if not allowed:
        raise DomainError(
            "INTERNAL_API_LOCAL_ONLY",
            "集成接口只允许服务器本机进程访问。",
            status_code=403,
        )


def build_router(prefix: str, *, internal: bool) -> APIRouter:
    dependencies = [Depends(require_internal_loopback)] if internal else None
    router = APIRouter(prefix=prefix, dependencies=dependencies)

    @router.get("/platforms")
    def list_platforms(request: Request) -> list[dict[str, Any]]:
        return _container(request).config.list_platforms()

    @router.get("/reputation/capabilities")
    def reputation_capabilities(request: Request) -> dict[str, Any]:
        return _container(request).reputation.capabilities()

    @router.get("/reputation/runs")
    def list_reputation_runs(
        request: Request,
        offset: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=200),
    ) -> dict[str, Any]:
        return _container(request).reputation.list_runs(offset, limit)

    @router.get("/reputation/schedule")
    def get_reputation_schedule(request: Request) -> dict[str, Any]:
        return _container(request).reputation.schedule_status()

    @router.post("/reputation/test-runs", status_code=202)
    def create_reputation_test_run(
        value: SyntheticRunCreate,
        request: Request,
    ) -> dict[str, Any]:
        return _container(request).reputation.create_synthetic(value.scenario_id)

    @router.get("/reputation/runs/{run_id}")
    def get_reputation_run(run_id: str, request: Request) -> dict[str, Any]:
        return _container(request).reputation.get_run(run_id, prefix)

    @router.post("/reputation/runs/{run_id}/retry-failed", status_code=202)
    def retry_reputation_failed(run_id: str, request: Request) -> dict[str, Any]:
        container = _container(request)
        result = container.reputation.retry_failed(run_id)
        container.reputation_coordinator.wake()
        return result

    @router.post("/reputation/runs/{run_id}/artifacts/retry")
    def retry_reputation_artifacts(run_id: str, request: Request) -> dict[str, Any]:
        return _container(request).reputation.generate_report(run_id)

    @router.delete("/reputation/runs/{run_id}", status_code=202)
    def delete_reputation_run(run_id: str, request: Request) -> dict[str, Any]:
        return _container(request).reputation.delete_official(run_id)

    @router.get("/reputation/delete-jobs/{job_id}")
    def get_reputation_delete_job(job_id: str, request: Request) -> dict[str, Any]:
        return _container(request).reputation.get_delete_job(job_id)

    @router.post("/reputation/delete-jobs/{job_id}/retry")
    def retry_reputation_delete_cleanup(job_id: str, request: Request) -> dict[str, Any]:
        return _container(request).reputation.retry_delete_cleanup(job_id)

    @router.delete("/reputation/test-runs/{run_id}")
    def delete_reputation_test_run(run_id: str, request: Request) -> dict[str, Any]:
        return _container(request).reputation.delete_synthetic(run_id)

    @router.get("/reputation/runs/{run_id}/report.txt")
    def download_reputation_report(run_id: str, request: Request) -> FileResponse:
        path = _container(request).reputation.get_file(run_id, "txt")
        return FileResponse(path, filename=path.name, media_type="text/plain; charset=utf-8")

    @router.get("/reputation/runs/{run_id}/export.xlsx")
    def download_reputation_xlsx(run_id: str, request: Request) -> FileResponse:
        path = _container(request).reputation.get_file(run_id, "xlsx")
        return FileResponse(
            path,
            filename=path.name,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    @router.get("/reputation/runs/{run_id}/evidence.zip")
    def download_reputation_evidence(run_id: str, request: Request) -> FileResponse:
        path = _container(request).reputation.evidence_zip(run_id)
        return FileResponse(path, filename=path.name, media_type="application/zip")

    @router.get("/reputation/evidence/{evidence_id}/full")
    def view_reputation_full_evidence(evidence_id: str, request: Request) -> FileResponse:
        path = _container(request).reputation.get_evidence_file(evidence_id, "full")
        return FileResponse(path, media_type="image/png", headers={"Cache-Control": "private"})

    @router.get("/reputation/evidence/{evidence_id}/metric")
    def view_reputation_metric_evidence(evidence_id: str, request: Request) -> FileResponse:
        path = _container(request).reputation.get_evidence_file(evidence_id, "metric")
        return FileResponse(path, media_type="image/png", headers={"Cache-Control": "private"})

    @router.get("/reputation/scope")
    def get_reputation_scope(request: Request) -> dict[str, Any]:
        return _container(request).reputation.get_scope()

    @router.post("/reputation/scope/vehicles")
    def create_reputation_scope_vehicle(
        value: ScopeVehicleCreateRequest,
        request: Request,
    ) -> dict[str, Any]:
        return _container(request).reputation.create_scope_vehicle(value)

    @router.patch("/reputation/scope/vehicles/{vehicle_id}")
    def update_reputation_scope_vehicle(
        vehicle_id: str,
        value: ScopeVehicleUpdateRequest,
        request: Request,
    ) -> dict[str, Any]:
        return _container(request).reputation.update_scope_vehicle(vehicle_id, value)

    @router.delete("/reputation/scope/vehicles/{vehicle_id}")
    def remove_reputation_scope_vehicle(
        vehicle_id: str,
        revision: int,
        request: Request,
    ) -> dict[str, Any]:
        return _container(request).reputation.remove_scope_vehicle(vehicle_id, revision)

    @router.post("/reputation/scope/vehicles/{vehicle_id}/restore")
    def restore_reputation_scope_vehicle(
        vehicle_id: str,
        value: ScopeVehicleRevisionRequest,
        request: Request,
    ) -> dict[str, Any]:
        return _container(request).reputation.restore_scope_vehicle(vehicle_id, value)

    @router.post("/reputation/scope/mappings/preview")
    def preview_reputation_mappings(
        value: MappingPasteRequest,
        request: Request,
    ) -> dict[str, Any]:
        return _container(request).reputation.preview_mappings(value)

    @router.put("/reputation/scope/mappings")
    def save_reputation_mappings(
        value: MappingPasteRequest,
        request: Request,
    ) -> dict[str, Any]:
        return _container(request).reputation.save_mappings(value)

    @router.post("/reputation/scope/mapping-validations")
    def validate_reputation_mappings(
        value: MappingValidationRequest,
        request: Request,
    ) -> dict[str, Any]:
        return _container(request).reputation.validate_mappings(value)

    @router.get("/reputation/scope/mapping-validations/{run_id}")
    def get_reputation_mapping_validation(run_id: str, request: Request) -> dict[str, Any]:
        return _container(request).reputation.get_mapping_validation(run_id, prefix)

    @router.get("/reputation/mapping-validations/attempts/{attempt_id}/full")
    def view_reputation_mapping_validation_full(attempt_id: str, request: Request) -> FileResponse:
        path = _container(request).reputation.get_mapping_validation_evidence(attempt_id, "full")
        return FileResponse(path, media_type="image/png", headers={"Cache-Control": "private"})

    @router.get("/reputation/mapping-validations/attempts/{attempt_id}/metric")
    def view_reputation_mapping_validation_metric(
        attempt_id: str, request: Request
    ) -> FileResponse:
        path = _container(request).reputation.get_mapping_validation_evidence(attempt_id, "metric")
        return FileResponse(path, media_type="image/png", headers={"Cache-Control": "private"})

    @router.get("/reputation/scope/publish-preview")
    def preview_reputation_scope_publish(request: Request) -> dict[str, Any]:
        return _container(request).reputation.publish_preview()

    @router.post("/reputation/scope/publish")
    def publish_reputation_scope(
        value: ScopePublishRequest,
        request: Request,
    ) -> dict[str, Any]:
        return _container(request).reputation.publish_scope(value)

    @router.get("/sentiment/config")
    def get_sentiment_config(request: Request) -> dict[str, Any]:
        return _container(request).sentiment.get_config()

    @router.put("/sentiment/config")
    def update_sentiment_config(value: SentimentConfigUpdate, request: Request) -> dict[str, Any]:
        if value.api_key is not None:
            host = request.client.host if request.client else ""
            loopback = host == "testclient"
            if not loopback:
                try:
                    loopback = ip_address(host).is_loopback
                except ValueError:
                    loopback = False
            if request.url.scheme != "https" and not loopback:
                raise DomainError(
                    "SENTIMENT_KEY_HTTPS_REQUIRED",
                    "远程页面必须通过 HTTPS 保存 API Key。",
                    status_code=403,
                )
        container = _container(request)
        result = container.sentiment.update_config(value)
        container.sentiment_worker.apply_runtime_config(
            result["model_code"], result["cloud_concurrency"]
        )
        container.events.publish("sentiment.config.changed", "sentiment-config")
        return result

    @router.post("/sentiment/config/test")
    def test_sentiment_config(request: Request) -> dict[str, Any]:
        container = _container(request)
        result = container.sentiment.test_connection()
        container.events.publish("sentiment.config.changed", "sentiment-config")
        return result

    @router.put("/platforms/{code}")
    def update_platform(code: str, value: PlatformConfigUpdate, request: Request) -> dict[str, Any]:
        container = _container(request)
        result = container.config.update_platform(code, value)
        container.events.publish("platform.changed", code, enabled=result["enabled"])
        return result

    @router.get("/extraction-plan")
    def get_extraction_plan(request: Request) -> dict[str, Any]:
        return _container(request).config.get_extraction_plan()

    @router.put("/extraction-plan")
    def update_extraction_plan(value: ExtractionPlanUpdate, request: Request) -> dict[str, Any]:
        container = _container(request)
        result = container.config.update_extraction_plan(value)
        container.events.publish(
            "extraction-plan.changed", "extraction-plan", summary_version=result["revision"]
        )
        return result

    @router.post("/extraction-rules/{rule_id}/restore")
    def restore_extraction_rule(rule_id: str, request: Request) -> dict[str, Any]:
        container = _container(request)
        result = container.config.restore_extraction_rule(rule_id)
        container.events.publish(
            "extraction-plan.changed", "extraction-plan", summary_version=result["revision"]
        )
        return result

    @router.get("/vehicles")
    def list_vehicles(request: Request) -> list[dict[str, Any]]:
        return _container(request).config.list_vehicles()

    @router.put("/circles/batch")
    def save_circles(value: CircleBatchUpdate, request: Request) -> dict[str, Any]:
        container = _container(request)
        result = container.config.save_circle_batch(value)
        container.events.publish("circles.changed", "circles")
        return result

    @router.get("/circles")
    def list_circles(request: Request) -> list[dict[str, Any]]:
        return _container(request).config.list_circles()

    @router.get("/circles/{circle_id}")
    def get_circle(circle_id: str, request: Request) -> dict[str, Any]:
        return _container(request).config.get_circle(circle_id)

    @router.post("/circles", status_code=201)
    def create_circle(value: CircleRow, request: Request) -> dict[str, Any]:
        container = _container(request)
        result = container.config.create_circle(value)
        container.events.publish("circles.changed", result["id"])
        return result

    @router.put("/circles/{circle_id}")
    def update_circle(circle_id: str, value: CircleRow, request: Request) -> dict[str, Any]:
        container = _container(request)
        result = container.config.update_circle(circle_id, value)
        container.events.publish("circles.changed", circle_id)
        return result

    @router.delete("/circles/{circle_id}")
    def delete_circle(circle_id: str, request: Request) -> dict[str, Any]:
        container = _container(request)
        result = container.config.delete_circle(circle_id)
        container.events.publish("circles.changed", circle_id)
        return result

    @router.post("/circles/{circle_id}/validate", status_code=202)
    def validate_circle(circle_id: str, request: Request) -> dict[str, Any]:
        return _container(request).config.create_validation_job(circle_id)

    @router.post("/circles/validate-unverified", status_code=202)
    def validate_unverified_circles(request: Request) -> dict[str, Any]:
        return _container(request).config.create_unverified_validation_jobs()

    @router.get("/validation-jobs/{job_id}")
    def validation_job(job_id: str, request: Request) -> dict[str, Any]:
        with _container(request).sessions() as db:
            job = db.get(ValidationJob, job_id)
            if not job:
                raise DomainError(
                    "VALIDATION_JOB_NOT_FOUND", "圈子验证任务不存在。", status_code=404
                )
            return validation_job_dict(job)

    @router.get("/manual-circle-history")
    def manual_history(request: Request) -> list[dict[str, Any]]:
        return _container(request).config.list_manual_history()

    @router.delete("/manual-circle-history")
    def clear_manual_history(request: Request) -> dict[str, Any]:
        return {"deleted_count": _container(request).config.delete_manual_history()}

    @router.delete("/manual-circle-history/{circle_id}")
    def delete_manual_history(circle_id: str, request: Request) -> dict[str, Any]:
        return {"deleted_count": _container(request).config.delete_manual_history(circle_id)}

    @router.post("/runs/manual", status_code=202)
    def create_manual_run(
        value: ManualRunCreate,
        request: Request,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> dict[str, Any]:
        container = _container(request)
        result = container.runs.create_manual(
            value,
            scope="internal" if internal else "api",
            header_key=idempotency_key if internal else None,
        )
        container.events.publish(
            "run.changed",
            result["id"],
            summary_version=result["summary_version"],
            status=result["status"],
        )
        return result

    @router.post("/runs/{run_id}/retry", status_code=202)
    def retry_run(
        run_id: str,
        request: Request,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> dict[str, Any]:
        if not idempotency_key:
            raise DomainError("IDEMPOTENCY_KEY_REQUIRED", "手动补提必须提供 Idempotency-Key。")
        container = _container(request)
        result = container.runs.retry(run_id, idempotency_key, "internal" if internal else "api")
        container.events.publish(
            "run.changed",
            result["id"],
            summary_version=result["summary_version"],
            status=result["status"],
        )
        return result

    @router.get("/runs")
    def list_runs(
        request: Request,
        offset: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=200),
        number: str | None = None,
        status: list[str] | None = Query(None),
        trigger_type: str | None = None,
        trigger_types: list[str] | None = Query(None),
        list_order: Literal["latest_reply", "latest_publish"] | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
    ) -> dict[str, Any]:
        return _container(request).runs.list_runs(
            offset,
            limit,
            number=number,
            statuses=status,
            trigger_type=trigger_type,
            trigger_types=trigger_types,
            list_order=list_order,
            created_from=created_from,
            created_to=created_to,
        )

    @router.get("/runs/{run_id}")
    def get_run(run_id: str, request: Request) -> dict[str, Any]:
        return _container(request).runs.get_run(run_id)

    @router.post("/runs/{run_id}/end-auth-wait")
    async def end_auth_wait(run_id: str, request: Request) -> dict[str, Any]:
        container = _container(request)
        result = container.runs.end_auth_wait(run_id)
        for platform_code in {task["platform_code"] for task in result.get("tasks", [])}:
            await container.auth.close_platform(platform_code)
        container.events.publish(
            "run.changed",
            run_id,
            summary_version=result["summary_version"],
            status=result["status"],
        )
        return result

    @router.delete("/runs/{run_id}")
    def delete_run(run_id: str, request: Request) -> dict[str, Any]:
        container = _container(request)
        evidence_paths, group_ids = container.screenshots.prepare_run_delete(run_id)
        paths = container.runs.delete_run(run_id)
        for raw in [*paths, *evidence_paths]:
            Path(raw).unlink(missing_ok=True)
        container.screenshots.reconcile_after_run_delete(group_ids)
        container.events.publish("run.deleted", run_id)
        return {"message": "提取批次及其关联数据已永久删除。"}

    @router.get("/runs/{run_id}/screenshots")
    def list_run_screenshots(run_id: str, request: Request) -> dict[str, Any]:
        return _container(request).screenshots.list_for_run(run_id, prefix)

    @router.get("/page-evidence/{evidence_id}/image")
    def view_page_evidence(evidence_id: str, request: Request) -> FileResponse:
        path = _container(request).screenshots.evidence_path(evidence_id)
        return FileResponse(path, media_type="image/png", headers={"Cache-Control": "private"})

    @router.get("/page-evidence/{evidence_id}/download")
    def download_page_evidence(evidence_id: str, request: Request) -> FileResponse:
        path = _container(request).screenshots.evidence_path(evidence_id)
        return FileResponse(path, media_type="image/png", filename=path.name)

    @router.get("/screenshot-groups/{group_id}/tiles/{tile_index}")
    def view_artifact_tile(group_id: str, tile_index: int, request: Request) -> FileResponse:
        path = _container(request).screenshots.artifact_file(group_id, tile_index)
        return FileResponse(
            path,
            media_type="image/png",
            headers={"Cache-Control": "private, max-age=31536000, immutable"},
        )

    @router.get("/screenshot-groups/{group_id}/download")
    def download_artifact(group_id: str, request: Request) -> FileResponse:
        path = _container(request).screenshots.artifact_file(group_id)
        return FileResponse(path, media_type="application/zip", filename=path.name)

    @router.post("/screenshot-groups/{group_id}/rebuild")
    def rebuild_artifact(group_id: str, request: Request) -> dict[str, Any]:
        rebuilt = _container(request).screenshots.rebuild(group_id, reason="manual_rebuild")
        return {"rebuilt": rebuilt}

    @router.get("/runs/{run_id}/posts")
    def list_posts(
        run_id: str,
        request: Request,
        offset: int = Query(0, ge=0),
        limit: int = Query(100, ge=1, le=500),
        title: str | None = None,
        circle: str | None = None,
        source_key: list[str] | None = Query(None),
        visibility: str | None = None,
        sentiment_result: Literal["negative", "non_negative", "unrelated"] | None = None,
        analysis_status: str | None = None,
        sort_by: str = Query("source", pattern="^(source|published_at|reply_count|like_count)$"),
        sort_direction: str = Query("asc", pattern="^(asc|desc)$"),
    ) -> dict[str, Any]:
        return _container(request).runs.posts(
            run_id,
            offset,
            limit,
            title=title,
            circle=circle,
            source_keys=source_key,
            visibility=visibility,
            sentiment_result=sentiment_result,
            analysis_status=analysis_status,
            sort_by=sort_by,
            sort_direction=sort_direction,
        )

    @router.get("/runs/{run_id}/posts/urls")
    def list_post_urls(
        run_id: str,
        request: Request,
        title: str | None = None,
        circle: str | None = None,
        source_key: list[str] | None = Query(None),
        visibility: str | None = None,
        sentiment_result: Literal["negative", "non_negative", "unrelated"] | None = None,
        analysis_status: str | None = None,
        sort_by: str = Query("source", pattern="^(source|published_at|reply_count|like_count)$"),
        sort_direction: str = Query("asc", pattern="^(asc|desc)$"),
    ) -> dict[str, Any]:
        return _container(request).runs.post_urls(
            run_id,
            title=title,
            circle=circle,
            source_keys=source_key,
            visibility=visibility,
            sentiment_result=sentiment_result,
            analysis_status=analysis_status,
            sort_by=sort_by,
            sort_direction=sort_direction,
        )

    @router.get("/runs/{run_id}/posts/{post_id}")
    def post_detail(run_id: str, post_id: str, request: Request) -> dict[str, Any]:
        return _container(request).runs.post_detail(run_id, post_id)

    @router.post("/runs/{run_id}/posts/{post_id}/media/resolve")
    def resolve_post_media(run_id: str, post_id: str, request: Request) -> dict[str, Any]:
        result = _container(request).worker.resolve_post_video_urls(run_id, post_id)
        result["playback_urls"] = [
            f"{prefix}/runs/{run_id}/posts/{post_id}/media/play/{index}"
            for index, _url in enumerate(result["video_urls"])
        ]
        return result

    @router.get("/runs/{run_id}/posts/{post_id}/media/play/{index}")
    def play_post_media(
        run_id: str,
        post_id: str,
        index: int,
        request: Request,
    ) -> RedirectResponse:
        target = _container(request).worker.cached_post_video_url(run_id, post_id, index)
        return RedirectResponse(
            target,
            status_code=307,
            headers={"Referrer-Policy": "no-referrer", "Cache-Control": "no-store"},
        )

    @router.post("/runs/{run_id}/posts/{post_id}/sentiment/manual-revisions")
    def revise_post_sentiment(
        run_id: str,
        post_id: str,
        value: ManualSentimentRevisionCreate,
        request: Request,
    ) -> dict[str, Any]:
        result = _container(request).sentiment.manual_revision(run_id, post_id, value)
        _container(request).screenshots.mark_all_dirty_for_post(post_id)
        _container(request).events.publish(
            "sentiment.changed", post_id, status=result["analysis_status"]
        )
        return result

    @router.get("/runs/{run_id}/posts/{post_id}/navigation")
    def post_navigation(
        run_id: str,
        post_id: str,
        request: Request,
        title: str | None = None,
        circle: str | None = None,
        source_key: list[str] | None = Query(None),
        visibility: str | None = None,
        sentiment_result: Literal["negative", "non_negative", "unrelated"] | None = None,
        analysis_status: str | None = None,
        sort_by: str = Query("source", pattern="^(source|published_at|reply_count|like_count)$"),
        sort_direction: str = Query("asc", pattern="^(asc|desc)$"),
    ) -> dict[str, Any]:
        return _container(request).runs.post_navigation(
            run_id,
            post_id,
            title=title,
            circle=circle,
            source_keys=source_key,
            visibility=visibility,
            sentiment_result=sentiment_result,
            analysis_status=analysis_status,
            sort_by=sort_by,
            sort_direction=sort_direction,
        )

    @router.get("/template-fields")
    def template_fields(
        request: Request,
        source_id: str | None = None,
    ) -> list[dict[str, str]]:
        return _container(request).templates.field_tags(source_id)

    @router.post("/templates")
    async def upload_template(
        request: Request,
        name: Annotated[str, Form()],
        file: Annotated[UploadFile, File()],
    ) -> dict[str, Any]:
        data = await file.read()
        return _container(request).templates.upload(name, file.filename or "template.xlsx", data)

    @router.get("/templates")
    def list_templates(request: Request) -> list[dict[str, Any]]:
        return _container(request).templates.list_templates()

    @router.get(
        "/templates/{template_id}/versions/{version_id}/download",
        response_class=FileResponse,
    )
    def download_template(template_id: str, version_id: str, request: Request) -> FileResponse:
        path, filename = _container(request).templates.template_path(template_id, version_id)
        return FileResponse(
            path,
            filename=filename,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    @router.delete("/templates/{template_id}")
    def hide_template(template_id: str, request: Request) -> dict[str, str]:
        _container(request).templates.hide_template(template_id)
        return {"message": "模板已从可选列表隐藏，历史版本继续保留。"}

    @router.post("/runs/{run_id}/exports")
    def create_export(run_id: str, value: ExportCreate, request: Request) -> dict[str, Any]:
        return _container(request).templates.create_export(run_id, value.template_version_id)

    @router.get("/exports/{export_id}/download", response_class=FileResponse)
    def download_export(export_id: str, request: Request) -> FileResponse:
        path = _container(request).templates.export_path(export_id)
        return FileResponse(
            path,
            filename=f"threadsnap-{export_id}.xlsx",
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    @router.get("/platforms/{code}/session")
    def session_status(code: str, request: Request) -> dict[str, Any]:
        return _container(request).session_store.status(code)

    @router.delete("/platforms/{code}/session")
    def clear_session(code: str, request: Request) -> dict[str, str]:
        container = _container(request)
        container.session_store.clear(code)
        container.events.publish("session.changed", code, status="missing")
        return {"message": "平台会话已清除。"}

    if internal:

        @router.post("/platforms/{code}/session/import")
        def import_session(code: str, value: SessionImport, request: Request) -> dict[str, str]:
            container = _container(request)
            container.session_store.import_state(code, value.storage_state)
            container.worker.resume_platform(code)
            container.events.publish("session.changed", code, status="valid")
            return {"message": "平台会话已加密保存，等待任务将自动续跑。"}

    @router.post("/platforms/{code}/auth/tasks", status_code=202)
    async def create_auth_task(
        code: str,
        request: Request,
        fresh: bool = False,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        return await _container(request).auth.create(code, fresh=fresh, run_id=run_id)

    @router.get("/auth/tasks/{task_id}")
    def auth_task(task_id: str, request: Request) -> dict[str, Any]:
        return _container(request).auth.get(task_id)

    return router


def create_app(settings: Settings | None = None) -> FastAPI:
    actual = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        container = Container(actual)
        app.state.container = container
        await container.start()
        try:
            yield
        finally:
            await container.stop()

    app = FastAPI(title="ThreadSnap API", version="0.1.0", lifespan=lifespan)
    app.add_exception_handler(DomainError, domain_error_handler)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {
                "field": ".".join(str(x) for x in error["loc"] if x != "body"),
                "reason": "字段格式或取值无效",
            }
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={
                "code": "REQUEST_INVALID",
                "message": "请求参数校验失败。",
                "details": details,
                "request_id": getattr(request.state, "request_id", ""),
            },
        )

    @app.exception_handler(OperationalError)
    async def database_operational_error(request: Request, exc: OperationalError) -> JSONResponse:
        if "database is locked" in str(exc).casefold():
            return JSONResponse(
                status_code=503,
                content={
                    "code": "DATABASE_BUSY",
                    "message": "数据库正在处理其他写入，请稍后重试。",
                    "details": [],
                    "request_id": getattr(request.state, "request_id", ""),
                },
                headers={"Retry-After": "1"},
            )
        return await unexpected_error(request, exc)

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content={
                "code": "INTERNAL_ERROR",
                "message": "服务处理请求时发生内部错误。",
                "details": [],
                "request_id": getattr(request.state, "request_id", ""),
            },
        )

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request.state.request_id = request.headers.get("X-Request-ID") or uuid7()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": "0.1.0"}

    app.include_router(build_router("/api/v1", internal=False))
    app.include_router(build_router("/internal/v1", internal=True))

    @app.get("/api/v1/events")
    async def event_stream(
        request: Request,
        last_event_id: int = Query(0, ge=0),
    ) -> StreamingResponse:
        """推送轻量变化信号，业务数据仍由普通 HTTP 接口返回。"""

        header_value = request.headers.get("Last-Event-ID")
        cursor = int(header_value) if header_value and header_value.isdigit() else last_event_id

        async def generate():
            nonlocal cursor
            yield ": connected\n\n"
            while True:
                if await request.is_disconnected():
                    break
                events = await asyncio.to_thread(
                    request.app.state.container.events.wait_after, cursor, 20.0
                )
                if not events:
                    yield ": heartbeat\n\n"
                    continue
                for event in events:
                    cursor = event["id"]
                    payload = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
                    yield f"id: {cursor}\nevent: {event['type']}\ndata: {payload}\n\n"

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.websocket("/api/v1/auth/tasks/{task_id}/stream")
    async def auth_stream(websocket: WebSocket, task_id: str) -> None:
        protocols = {
            item.strip()
            for item in websocket.headers.get("sec-websocket-protocol", "").split(",")
            if item.strip()
        }
        prefix = "threadsnap-ticket."
        ticket = next(
            (item.removeprefix(prefix) for item in protocols if item.startswith(prefix)),
            "",
        )
        if "threadsnap-auth" not in protocols:
            ticket = ""
        await websocket.app.state.container.auth.stream(task_id, ticket, websocket)

    return app


app = create_app()
