"""固定十四天关联链保留；持久清理意图连接数据库事务与文件系统。"""

from __future__ import annotations

import json
import logging
import os
import shutil
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import case, func, or_, select

from .models import (
    CirclePageEvidence,
    CircleTask,
    ExportRecord,
    ExtractionRun,
    ManualSentimentRevision,
    PostSnapshot,
    ReputationDeleteJob,
    ReputationResult,
    ReputationRun,
    ScreenshotArtifactContribution,
    ScreenshotArtifactGroup,
    ScreenshotArtifactTile,
    ScreenshotArtifactVersion,
    SentimentAnalysis,
)
from .services import TERMINAL_STATUSES, related_run_ids

LOGGER = logging.getLogger(__name__)
RETENTION_DAYS = 14
POLL_SECONDS = 60


def _now(value: datetime | None) -> datetime:
    """保留边界按连续时长计算，不将十四天截断为自然日。"""
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is None:
        raise ValueError("保留时间必须带时区。")
    return value.astimezone(timezone.utc)


def _write_json(path: Path, data: dict[str, Any]) -> None:
    """同目录原子发布并同步文件内容；旧意图在异常时保持可读。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
    if os.name != "nt":
        # Linux 上同时持久化目录项，避免断电后数据库已删而清理意图重命名丢失。
        descriptor = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


class RetentionService:
    """只清理已终态且无在途使用的整链；不持有用户可变保留配置。"""

    def __init__(
        self, factory, settings, runs, screenshots, reputation, activity, event_publisher=None
    ):
        self.factory = factory
        self.settings = settings
        self.runs = runs
        self.screenshots = screenshots
        self.reputation = reputation
        self.activity = activity
        self.event_publisher = event_publisher
        self.root = settings.data_dir / "retention"
        if self.root.is_symlink() or not self.root.resolve().is_relative_to(
            settings.data_dir.resolve()
        ):
            raise ValueError("保留清理意图目录越界。")
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self._process_lock = threading.Lock()

    def start(self) -> None:
        """应用开启后台工作时启动；生命周期开关由容器统一负责。"""
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._loop, name="threadsnap-retention", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        """停止领取下一条链，正在提交的一条链沿既有意图安全收口。"""
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=10)

    def _loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                self.process_once()
            except Exception:
                LOGGER.exception("业务保留轮询失败，将在下一轮恢复")
            self.stop_event.wait(POLL_SECONDS)

    @staticmethod
    def _component(value: str) -> str:
        if (
            not value
            or value in {".", ".."}
            or Path(value).name != value
            or "/" in value
            or "\\" in value
        ):
            raise ValueError("清理身份不是安全的单级目录名。")
        return value

    def _owned_paths(self, kind: str, run_ids: list[str], group_ids: list[str]) -> list[Path]:
        """只允许身份派生的完整目录，不接受数据库或清单指定任意删除根。"""
        if kind == "extraction":
            pairs = [(self.settings.screenshot_evidence_dir, x) for x in run_ids]
            pairs += [(self.settings.export_dir, x) for x in run_ids]
            pairs += [(self.settings.screenshot_artifact_dir, x) for x in group_ids]
        elif kind == "reputation":
            pairs = [(self.settings.reputation_dir, x) for x in run_ids]
        else:
            raise ValueError("未知清理类型。")
        data = self.settings.data_dir.resolve()
        paths = []
        for root, key in pairs:
            candidate = root / self._component(key)
            resolved_root = root.resolve()
            if resolved_root == data or not resolved_root.is_relative_to(data):
                raise ValueError("清理根目录不在应用数据目录内。")
            resolved = candidate.resolve()
            if (
                candidate.is_symlink()
                or resolved == resolved_root
                or not resolved.is_relative_to(resolved_root)
            ):
                raise ValueError("清理目标越界或使用了目录链接。")
            # 拒绝内部链接，防止证据路径实际引用其他链或应用目录外内容。
            if candidate.exists():
                if not candidate.is_dir():
                    raise ValueError("批次清理目标不是目录。")
                for child in candidate.rglob("*"):
                    if child.is_symlink() or not child.resolve().is_relative_to(resolved):
                        raise ValueError("清理目录含越界链接。")
            paths.append(resolved)
        return sorted(set(paths))

    @staticmethod
    def _validate_references(references: list[str], paths: list[Path]) -> None:
        for raw in references:
            if raw and not any(Path(raw).resolve().is_relative_to(root) for root in paths):
                raise ValueError("文件记录不属于本关联链目录，禁止清理。")

    @staticmethod
    def _chains(rows, parent_name: str) -> list[list[str]]:
        by_id = {row.id: row for row in rows}
        grouped: dict[str, list[str]] = {}
        for row in rows:
            current = row
            seen = {row.id}
            while (parent := getattr(current, parent_name)) in by_id:
                if parent in seen:
                    raise ValueError("关联链出现循环，禁止自动清理。")
                seen.add(parent)
                current = by_id[parent]
            grouped.setdefault(current.id, []).append(row.id)
        return list(grouped.values())

    @staticmethod
    def _activity_summary(db) -> dict[str, dict[str, Any]]:
        """全轮按批次聚合业务时间，避免每条链重新扫描体积较大的帖子表。"""
        result: dict[str, dict[str, Any]] = {}

        def summary(key):
            return result.setdefault(key, {"moments": [], "analysis": False, "tasks": False})

        statements = [
            select(PostSnapshot.run_id, func.max(PostSnapshot.sentiment_updated_at)).group_by(
                PostSnapshot.run_id
            ),
            select(PostSnapshot.run_id, func.max(ManualSentimentRevision.created_at))
            .join(ManualSentimentRevision, ManualSentimentRevision.post_id == PostSnapshot.id)
            .group_by(PostSnapshot.run_id),
            select(ReputationResult.run_id, func.max(ReputationResult.collected_at)).group_by(
                ReputationResult.run_id
            ),
        ]
        for statement in statements:
            for key, stamp in db.execute(statement):
                if stamp:
                    summary(key)["moments"].append(stamp)
        for key, stamp, active in db.execute(
            select(
                PostSnapshot.run_id,
                func.max(SentimentAnalysis.finished_at),
                func.max(
                    case(
                        (SentimentAnalysis.status.in_(["analysis_queued", "analysis_running"]), 1),
                        else_=0,
                    )
                ),
            )
            .join(SentimentAnalysis, SentimentAnalysis.post_id == PostSnapshot.id)
            .group_by(PostSnapshot.run_id)
        ):
            if stamp:
                summary(key)["moments"].append(stamp)
            summary(key)["analysis"] = bool(active)
        for key in db.scalars(
            select(CircleTask.run_id).where(CircleTask.status.not_in(TERMINAL_STATUSES)).distinct()
        ):
            summary(key)["tasks"] = True
        return result

    def _inspect(
        self,
        db,
        kind: str,
        run_ids: list[str],
        now: datetime,
        activity_summary: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        model = ExtractionRun if kind == "extraction" else ReputationRun
        rows = list(db.scalars(select(model).where(model.id.in_(run_ids))))
        parent_name = "related_run_id" if kind == "extraction" else "root_run_id"
        root = next((row for row in rows if getattr(row, parent_name) not in run_ids), rows[0])
        item = {
            "kind": kind,
            "root_id": root.id,
            "run_ids": sorted(run_ids),
            "numbers": [row.number for row in rows],
            "paths": [],
            "group_ids": [],
            "last_activity_at": None,
            "expires_at": None,
            "reason": None,
        }
        if any(row.status not in TERMINAL_STATUSES or row.finished_at is None for row in rows):
            item["reason"] = "chain_not_terminal"
            return item
        moments = [row.finished_at for row in rows]
        references: list[str] = []
        if activity_summary is not None:
            for run_id in run_ids:
                moments.extend(activity_summary.get(run_id, {}).get("moments", []))
        if kind == "extraction":
            post_ids = select(PostSnapshot.id).where(PostSnapshot.run_id.in_(run_ids))
            if activity_summary is None:
                for owner, column in (
                    (ManualSentimentRevision, ManualSentimentRevision.created_at),
                    (SentimentAnalysis, SentimentAnalysis.finished_at),
                ):
                    stamp = db.scalar(select(func.max(column)).where(owner.post_id.in_(post_ids)))
                    if stamp:
                        moments.append(stamp)
                stamp = db.scalar(
                    select(func.max(PostSnapshot.sentiment_updated_at)).where(
                        PostSnapshot.run_id.in_(run_ids)
                    )
                )
                if stamp:
                    moments.append(stamp)
                tasks_busy = db.scalar(
                    select(CircleTask.id)
                    .where(
                        CircleTask.run_id.in_(run_ids), CircleTask.status.not_in(TERMINAL_STATUSES)
                    )
                    .limit(1)
                )
                analysis_busy = db.scalar(
                    select(SentimentAnalysis.id)
                    .where(
                        SentimentAnalysis.post_id.in_(post_ids),
                        SentimentAnalysis.status.in_(["analysis_queued", "analysis_running"]),
                    )
                    .limit(1)
                )
            else:
                tasks_busy = any(activity_summary.get(key, {}).get("tasks") for key in run_ids)
                analysis_busy = any(
                    activity_summary.get(key, {}).get("analysis") for key in run_ids
                )
            if tasks_busy:
                item["reason"] = "task_in_progress"
            if analysis_busy:
                item["reason"] = "analysis_in_progress"
            if max(moments) + timedelta(days=RETENTION_DAYS) > now:
                item.update(
                    reason=item["reason"] or "within_retention",
                    last_activity_at=max(moments).isoformat(),
                    expires_at=(max(moments) + timedelta(days=RETENTION_DAYS)).isoformat(),
                )
                return item
            groups = list(
                db.scalars(
                    select(ScreenshotArtifactGroup.id).where(
                        or_(
                            ScreenshotArtifactGroup.chain_root_run_id.in_(run_ids),
                            ScreenshotArtifactGroup.id.in_(
                                select(ScreenshotArtifactContribution.group_id).where(
                                    ScreenshotArtifactContribution.run_id.in_(run_ids)
                                )
                            ),
                        )
                    )
                )
            )
            item["group_ids"] = groups
            if db.scalar(
                select(ScreenshotArtifactContribution.id)
                .where(
                    ScreenshotArtifactContribution.group_id.in_(groups),
                    ScreenshotArtifactContribution.run_id.not_in(run_ids),
                )
                .limit(1)
            ):
                item["reason"] = "shared_artifact_group"
            for evidence in db.scalars(
                select(CirclePageEvidence).where(CirclePageEvidence.run_id.in_(run_ids))
            ):
                references.extend([evidence.screenshot_path, evidence.manifest_path])
            references.extend(
                db.scalars(select(ExportRecord.file_path).where(ExportRecord.run_id.in_(run_ids)))
            )
            versions = list(
                db.scalars(
                    select(ScreenshotArtifactVersion).where(
                        ScreenshotArtifactVersion.group_id.in_(groups)
                    )
                )
            )
            for version in versions:
                references.append(version.package_path)
                references.extend(tile.get("path", "") for tile in version.tiles)
            references.extend(
                db.scalars(
                    select(ScreenshotArtifactTile.file_path).where(
                        ScreenshotArtifactTile.version_id.in_([version.id for version in versions])
                    )
                )
            )
        else:
            if root.source_type not in {"scheduled", "real_acceptance", "synthetic"}:
                item["reason"] = "unsupported_reputation_root"
            if any(row.report_status == "generating" for row in rows):
                item["reason"] = "report_in_progress"
            if activity_summary is None:
                stamp = db.scalar(
                    select(func.max(ReputationResult.collected_at)).where(
                        ReputationResult.run_id.in_(run_ids)
                    )
                )
                if stamp:
                    moments.append(stamp)
            # 报告完成是有效业务收口；下载或仅生成 ZIP 不刷新此时间。
            moments.extend(row.report_generated_at for row in rows if row.report_generated_at)
        last = max(moments)
        item["last_activity_at"] = last.isoformat()
        item["expires_at"] = (last + timedelta(days=RETENTION_DAYS)).isoformat()
        if not item["reason"] and last + timedelta(days=RETENTION_DAYS) > now:
            item["reason"] = "within_retention"
        try:
            paths = self._owned_paths(kind, run_ids, item["group_ids"])
            self._validate_references(references, paths)
            item["paths"] = [str(path) for path in paths]
        except ValueError as exc:
            item["reason"] = "unsafe_path"
            item["detail"] = str(exc)
        return item

    def preview(self, now: datetime | None = None) -> dict[str, Any]:
        """只读枚举到期与跳过链，用于备份、生产预览与删除集合对账。"""
        current = _now(now)
        result = {
            "now": current.isoformat(),
            "cutoff": (current - timedelta(days=RETENTION_DAYS)).isoformat(),
            "eligible": [],
            "skipped": [],
            "pending": [],
        }
        with self.factory() as db:
            summary = self._activity_summary(db)
            for kind, model, parent in (
                ("extraction", ExtractionRun, "related_run_id"),
                ("reputation", ReputationRun, "root_run_id"),
            ):
                for ids in self._chains(list(db.scalars(select(model))), parent):
                    item = self._inspect(db, kind, ids, current, summary)
                    result["skipped" if item["reason"] else "eligible"].append(item)
            result["pending"].extend(
                {"kind": "reputation", "job_id": row.id, "status": row.status}
                for row in db.scalars(
                    select(ReputationDeleteJob).where(ReputationDeleteJob.status != "success")
                )
            )
        if self.root.exists():
            result["pending"].extend(
                {"kind": "extraction", "manifest": str(path)}
                for path in sorted(self.root.glob("extraction-*.json"))
            )
        return result

    def _recheck(self, kind: str, root_id: str, now: datetime) -> dict[str, Any] | None:
        with self.factory() as db:
            model = ExtractionRun if kind == "extraction" else ReputationRun
            if not db.get(model, root_id):
                return None
            if kind == "extraction":
                ids = related_run_ids(db, root_id)
            else:
                ids = list(
                    db.scalars(
                        select(ReputationRun.id).where(
                            or_(ReputationRun.id == root_id, ReputationRun.root_run_id == root_id)
                        )
                    )
                )
            return self._inspect(db, kind, ids, now)

    def _remove_paths(self, paths: list[Path]) -> None:
        """失败不吞掉，持久意图下轮继续；不依赖文件 mtime 或扫描其他目录。"""
        for path in paths:
            if path.exists():
                shutil.rmtree(path)

    def _delete_extraction(self, item: dict[str, Any]) -> None:
        plan_path = self.root / f"extraction-{self._component(item['root_id'])}.json"
        plan = {key: item[key] for key in ("kind", "root_id", "run_ids", "group_ids", "paths")}
        plan["schema"] = "threadsnap.retention.v1"
        # 持久意图先于数据库提交，进程在任意一步停止仍能按数据库存在性继续。
        _write_json(plan_path, plan)
        self.runs.delete_chain(item["run_ids"], item["group_ids"])
        self._finish_extraction(plan_path, plan)

    def _finish_extraction(self, path: Path, plan: dict[str, Any]) -> None:
        paths = self._owned_paths("extraction", plan["run_ids"], plan["group_ids"])
        if sorted(map(str, paths)) != sorted(plan["paths"]):
            raise ValueError("持久清理清单路径与批次身份不一致。")
        with self.factory() as db:
            if db.scalar(
                select(ExtractionRun.id).where(ExtractionRun.id.in_(plan["run_ids"])).limit(1)
            ):
                raise ValueError("数据库尚未提交整链删除，不能回收文件。")
            if db.scalar(
                select(ScreenshotArtifactGroup.id)
                .where(ScreenshotArtifactGroup.id.in_(plan["group_ids"]))
                .limit(1)
            ):
                raise ValueError("成果组仍被数据库持有，不能回收文件。")
        self._remove_paths(paths)
        path.unlink(missing_ok=True)
        if self.event_publisher:
            for run_id in plan["run_ids"]:
                self.event_publisher("run.deleted", run_id)

    def _resume_plan(self, path: Path, now: datetime) -> str | None:
        plan = json.loads(path.read_text(encoding="utf-8"))
        if plan.get("schema") != "threadsnap.retention.v1" or plan.get("kind") != "extraction":
            raise ValueError("未知清理意图格式。")
        expected = self.root / f"extraction-{self._component(plan['root_id'])}.json"
        if path != expected:
            raise ValueError("清理意图文件名与批次不一致。")
        # 即使数据库仍在，也先检查计划路径，不能以重算计划掩盖被篡改的旧意图。
        expected_paths = self._owned_paths("extraction", plan["run_ids"], plan["group_ids"])
        if sorted(map(str, expected_paths)) != sorted(plan["paths"]):
            raise ValueError("清理意图存在越界路径。")
        current = self._recheck("extraction", plan["root_id"], now)
        if current:
            if current["reason"]:
                # 数据库提交前被恢复业务重新使用，旧意图不得继续删除。
                path.unlink()
                return None
            self._delete_extraction(current)
        else:
            self._finish_extraction(path, plan)
        return plan["root_id"]

    def process_once(self, now: datetime | None = None, force: bool = False) -> dict[str, Any]:
        """按链短暂取得排他权，忙或失败不记当日完成，并允许下一轮续清。"""
        if not self._process_lock.acquire(blocking=False):
            return {"status": "busy", "completed": [], "failed": [], "busy": True}
        try:
            return self._process_once(_now(now), force)
        finally:
            self._process_lock.release()

    def _process_once(self, current: datetime, force: bool) -> dict[str, Any]:
        local = current.astimezone(ZoneInfo("Asia/Shanghai"))
        result: dict[str, Any] = {
            "status": "complete",
            "completed": [],
            "failed": [],
            "busy": False,
        }
        state_path = self.root / "state.json"
        state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
        with self.factory() as db:
            pending = db.scalar(
                select(ReputationDeleteJob.id)
                .where(ReputationDeleteJob.status != "success")
                .limit(1)
            )
        pending = pending or (self.root.exists() and any(self.root.glob("extraction-*.json")))
        if not force and (
            local.hour < 3
            or (state.get("completed_date") == local.date().isoformat() and not pending)
        ):
            result["status"] = "not_due"
            return result
        with self.activity.maintenance() as acquired:
            if not acquired:
                return {**result, "status": "busy", "busy": True}
            snapshot = self.preview(current)
        work = [("pending", item) for item in snapshot["pending"]]
        work += [("candidate", item) for item in snapshot["eligible"]]
        for mode, item in work:
            if self.stop_event.is_set():
                result["busy"] = True
                break
            with self.activity.maintenance() as acquired:
                if not acquired:
                    result["busy"] = True
                    break
                identity = item.get("root_id") or item.get("job_id") or item.get("manifest")
                try:
                    if mode == "pending":
                        if item["kind"] == "extraction":
                            identity = self._resume_plan(Path(item["manifest"]), current)
                            if identity is None:
                                continue
                        else:
                            with self.factory() as db:
                                pending_job = db.get(ReputationDeleteJob, item["job_id"])
                                pending_root = pending_job.root_run_id if pending_job else None
                            identity = pending_root or identity
                            fresh = (
                                self._recheck("reputation", pending_root, current)
                                if pending_root
                                else None
                            )
                            if fresh and fresh["reason"]:
                                # 数据库提交前发生新的补跑/交付后，旧失败意图不能越过保留时钟。
                                result["busy"] = True
                                continue
                            job = self.reputation.retry_delete_cleanup(item["job_id"])
                            if job["status"] != "success":
                                raise RuntimeError(job.get("error_message") or job["status"])
                    else:
                        fresh = self._recheck(item["kind"], item["root_id"], current)
                        if not fresh:
                            continue
                        if fresh["reason"]:
                            result["busy"] = True
                            continue
                        if fresh["kind"] == "extraction":
                            self._delete_extraction(fresh)
                        else:
                            job = self.reputation.delete_official(
                                fresh["root_id"], allow_non_scheduled=True
                            )
                            if job["status"] != "success":
                                raise RuntimeError(job.get("error_message") or job["status"])
                    result["completed"].append(identity)
                except Exception as exc:
                    LOGGER.exception("保留清理未完成，已保留重试入口：%s", identity)
                    result["failed"].append({"id": identity, "error": str(exc)})
        # 旧链因真实分析/报告等待而跳过时，当日继续尝试；普通历史 dirty 不阻挡过期。
        blocked = {
            "chain_not_terminal",
            "task_in_progress",
            "analysis_in_progress",
            "report_in_progress",
        }
        result["busy"] = result["busy"] or any(
            item["reason"] in blocked for item in snapshot["skipped"]
        )
        unsafe = [
            item
            for item in snapshot["skipped"]
            if item["reason"] in {"unsafe_path", "shared_artifact_group"}
        ]
        result["failed"].extend({"id": item["root_id"], "error": item["reason"]} for item in unsafe)
        if result["failed"]:
            result["status"] = "partial_failure"
        elif result["busy"]:
            result["status"] = "deferred"
        else:
            _write_json(
                state_path,
                {"completed_date": local.date().isoformat(), "completed_at": current.isoformat()},
            )
        return result
