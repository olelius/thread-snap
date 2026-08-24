"""垂媒口碑巡检领域服务与隔离合成验收运行。"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import shutil
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

from openpyxl import Workbook
from openpyxl.drawing.image import Image as WorksheetImage
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from PIL import Image, ImageDraw
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from .config import Settings
from .errors import DomainError
from .ids import uuid7
from .models import (
    ReputationEvidence,
    ReputationResult,
    ReputationRun,
    ReputationScopeDraft,
    ReputationScopeVersion,
)

FIXTURE_VERSION = "reputation-synthetic-v1"
PLATFORM_CODE = "dongchedi"
PLATFORM_NAME = "懂车帝"
SCENARIOS: dict[str, dict[str, str]] = {
    "baseline_initialization": {
        "name": "基线初始化",
        "description": "27款车型首次建档，全量证据，不计算涨跌。",
    },
    "daily_mixed_changes": {
        "name": "日常混合变化",
        "description": "覆盖上涨、下降、分化、无变化和异常分支。",
    },
    "month_end_mixed_changes": {
        "name": "月末混合变化",
        "description": "沿用前日变化并验证27项全量页面证据。",
    },
}

GREEN_FILL = PatternFill("solid", fgColor="E2F0D9")
RED_FILL = PatternFill("solid", fgColor="F4CCCC")
NEUTRAL_FILL = PatternFill("solid", fgColor="F8FAFC")
HEADER_FILL = PatternFill("solid", fgColor="E8EEF8")


class SyntheticRunCreate(BaseModel):
    scenario_id: Literal[
        "baseline_initialization", "daily_mixed_changes", "month_end_mixed_changes"
    ]


class MappingPasteRow(BaseModel):
    vehicle_id: str
    platform_vehicle_id: str
    platform_url: str
    platform_display_name: str


class MappingPasteRequest(BaseModel):
    revision: int
    platform_code: str
    rows: list[MappingPasteRow]


class ScopePublishRequest(BaseModel):
    revision: int
    initial_review_acknowledged: bool = False


@dataclass(frozen=True)
class SyntheticVehicle:
    vehicle_id: str
    series_name: str
    vehicle_name: str
    role: str
    role_position: int
    vehicle_position: int


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _text_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _metric(
    current: Decimal | None,
    baseline: Decimal | None,
    *,
    inverse: bool = False,
    state: str = "available",
    raw: str | None = None,
    baseline_raw: str | None = None,
) -> dict[str, Any]:
    """按页面可见十进制值生成一个指标的比较投影。"""

    if state != "available":
        return {
            "raw": raw,
            "value": None,
            "baseline_raw": baseline_raw,
            "baseline_value": None,
            "delta": None,
            "direction": "none",
            "tone": "neutral",
            "comparison_status": state,
        }
    if current is None:
        raise ValueError("available 指标必须提供当前值")
    current_text = raw or format(current, "f")
    if baseline is None:
        return {
            "raw": current_text,
            "value": format(current, "f"),
            "baseline_raw": None,
            "baseline_value": None,
            "delta": None,
            "direction": "none",
            "tone": "neutral",
            "comparison_status": "no_baseline",
        }
    delta = current - baseline
    if delta == 0:
        direction = "same"
        tone = "neutral"
    else:
        direction = "up" if delta > 0 else "down"
        positive = delta < 0 if inverse else delta > 0
        tone = "positive" if positive else "negative"
    return {
        "raw": current_text,
        "value": format(current, "f"),
        "baseline_raw": baseline_raw or format(baseline, "f"),
        "baseline_value": format(baseline, "f"),
        "delta": format(delta, "+f"),
        "direction": direction,
        "tone": tone,
        "comparison_status": "comparable",
    }


def _vehicles() -> list[SyntheticVehicle]:
    values: list[SyntheticVehicle] = []
    for index in range(27):
        focus = index < 14
        role_position = index + 1 if focus else index - 13
        values.append(
            SyntheticVehicle(
                vehicle_id=f"synthetic-{index + 1:02d}",
                series_name=f"{'重点' if focus else '竞品'}车系{(index // 5) + 1}",
                vehicle_name=f"{'重点' if focus else '竞品'}车型{role_position:02d}",
                role="focus" if focus else "competitor",
                role_position=0 if focus else 1,
                vehicle_position=role_position,
            )
        )
    return values


def _scenario_rows(scenario_id: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    baseline_mode = scenario_id == "baseline_initialization"
    month_end = scenario_id == "month_end_mixed_changes"
    for index, vehicle in enumerate(_vehicles()):
        score_base = Decimal("3.80") + Decimal(index) / Decimal(100)
        rank_base = Decimal(5 + (index % 5))
        volume_base = Decimal(500 + index * 37)
        pattern = index % 9
        status = "success"
        error_code = None
        error_message = None
        if baseline_mode:
            score = _metric(score_base, None)
            rank = _metric(rank_base, None, inverse=True)
            volume = _metric(volume_base, None)
        elif pattern == 0:
            score = _metric(score_base + Decimal("0.12"), score_base)
            rank = _metric(rank_base - 1, rank_base, inverse=True)
            volume = _metric(volume_base + 120, volume_base)
        elif pattern == 1:
            score = _metric(score_base - Decimal("0.08"), score_base)
            rank = _metric(rank_base + 2, rank_base, inverse=True)
            volume = _metric(volume_base - 80, volume_base)
        elif pattern == 2:
            score = _metric(score_base + Decimal("0.05"), score_base)
            rank = _metric(rank_base + 1, rank_base, inverse=True)
            volume = _metric(volume_base, volume_base)
        elif pattern == 3:
            score = _metric(score_base, score_base)
            rank = _metric(rank_base, rank_base, inverse=True)
            volume = _metric(volume_base, volume_base)
        elif pattern == 4:
            score = _metric(score_base, score_base)
            rank = _metric(rank_base, rank_base, inverse=True)
            volume = _metric(volume_base + 300, volume_base)
        elif pattern == 5:
            score = _metric(score_base, None)
            rank = _metric(rank_base, None, inverse=True)
            volume = _metric(volume_base, None)
        elif pattern == 6:
            score = _metric(None, None, state="not_available", raw="暂无评分")
            rank = _metric(None, None, state="not_available", raw="暂无排名")
            volume = _metric(volume_base, volume_base)
        elif pattern == 7:
            score = _metric(None, None, state="unknown")
            rank = _metric(None, None, state="unknown")
            volume = _metric(None, None, state="unknown")
            status = "failed"
            error_code = "SYNTHETIC_UNKNOWN"
            error_message = "合成场景：页面结构无法可靠解析。"
        else:
            score = _metric(None, None, state="auth_required")
            rank = _metric(None, None, state="auth_required")
            volume = _metric(None, None, state="auth_required")
            status = "failed"
            error_code = "AUTH_REQUIRED"
            error_message = "合成场景：共享平台会话需要更新。"
        changed_score_or_rank = any(
            item["direction"] in {"up", "down"} for item in (score, rank)
        )
        evidence_required = baseline_mode or month_end or (
            vehicle.role == "focus" and changed_score_or_rank
        )
        rows.append(
            {
                "vehicle": vehicle,
                "status": status,
                "error_code": error_code,
                "error_message": error_message,
                "metrics": {"score": score, "rank": rank, "volume": volume},
                "evidence_required": evidence_required,
            }
        )
    return rows


class ReputationService:
    """口碑巡检查询、范围管理和隔离合成运行服务。"""

    def __init__(
        self,
        sessions: sessionmaker[Session],
        settings: Settings,
        *,
        event_publisher=None,
    ) -> None:
        self.sessions = sessions
        self.settings = settings
        self.event_publisher = event_publisher

    @property
    def synthetic_enabled(self) -> bool:
        return (
            self.settings.runtime_mode == "test"
            and self.settings.enable_reputation_synthetic_runs
            and self.settings.reputation_test_database
        )

    def capabilities(self) -> dict[str, Any]:
        return {
            "reputation_synthetic_runs": self.synthetic_enabled,
            "real_adapter_status": "not_configured",
            "real_adapter_message": "真实口碑页面合同尚未提供，当前不以猜测选择器访问平台。",
            "scenarios": [
                {"id": key, **value} for key, value in SCENARIOS.items()
            ]
            if self.synthetic_enabled
            else [],
        }

    def _require_synthetic(self) -> None:
        if not self.synthetic_enabled:
            raise DomainError(
                "REPUTATION_SYNTHETIC_DISABLED",
                "手动运行测试只在显式测试模式和隔离测试数据库中开放。",
                status_code=404,
            )

    def list_runs(self, offset: int = 0, limit: int = 50) -> dict[str, Any]:
        with self.sessions() as db:
            total = db.scalar(select(func.count()).select_from(ReputationRun)) or 0
            runs = db.scalars(
                select(ReputationRun)
                .order_by(ReputationRun.created_at.desc(), ReputationRun.id.desc())
                .offset(offset)
                .limit(limit)
            ).all()
            return {
                "items": [self._run_dict(run) for run in runs],
                "total": int(total),
                "offset": offset,
                "limit": limit,
            }

    def get_run(self, run_id: str, prefix: str = "/api/v1") -> dict[str, Any]:
        with self.sessions() as db:
            run = db.get(ReputationRun, run_id)
            if not run:
                raise DomainError(
                    "REPUTATION_RUN_NOT_FOUND", "口碑巡检运行不存在。", status_code=404
                )
            results = db.scalars(
                select(ReputationResult)
                .where(ReputationResult.run_id == run_id)
                .order_by(
                    ReputationResult.role_position,
                    ReputationResult.vehicle_position,
                    ReputationResult.id,
                )
            ).all()
            evidence_by_result = {
                item.result_id: item
                for item in db.scalars(
                    select(ReputationEvidence).where(
                        ReputationEvidence.result_id.in_([row.id for row in results])
                    )
                ).all()
            }
            payload = self._run_dict(run)
            payload["results"] = [
                self._result_dict(row, evidence_by_result.get(row.id), prefix) for row in results
            ]
            payload["downloads"] = {
                "txt": f"{prefix}/reputation/runs/{run.id}/report.txt",
                "xlsx": f"{prefix}/reputation/runs/{run.id}/export.xlsx",
                "evidence_zip": f"{prefix}/reputation/runs/{run.id}/evidence.zip",
            }
            return payload

    def create_synthetic(self, scenario_id: str) -> dict[str, Any]:
        self._require_synthetic()
        if scenario_id not in SCENARIOS:
            raise DomainError("REPUTATION_SCENARIO_UNKNOWN", "未知的口碑合成场景。")
        now = datetime.now(timezone.utc)
        rows = _scenario_rows(scenario_id)
        input_hash = _text_hash(
            {
                "fixture_version": FIXTURE_VERSION,
                "scenario_id": scenario_id,
                "rows": [
                    {
                        "vehicle_id": item["vehicle"].vehicle_id,
                        "metrics": item["metrics"],
                        "status": item["status"],
                    }
                    for item in rows
                ],
            }
        )
        run_id = uuid7()
        run_number = f"RP-T-{now:%Y%m%d-%H%M%S}-{run_id[-4:].upper()}"
        run_type = {
            "baseline_initialization": "baseline_initialization",
            "daily_mixed_changes": "daily",
            "month_end_mixed_changes": "month_end",
        }[scenario_id]
        run_dir = self.settings.reputation_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        failures = sum(1 for row in rows if row["status"] != "success")
        required = sum(1 for row in rows if row["evidence_required"])
        run = ReputationRun(
            id=run_id,
            number=run_number,
            source_type="synthetic",
            scenario_id=scenario_id,
            fixture_version=FIXTURE_VERSION,
            input_hash=input_hash,
            run_type=run_type,
            planned_date=now.astimezone(ZoneInfo(self.settings.timezone)).date().isoformat(),
            status="partial_success" if failures else "success",
            platform_codes=[PLATFORM_CODE],
            planned_count=len(rows),
            completed_count=len(rows) - failures,
            failed_count=failures,
            required_evidence_count=required,
            complete_evidence_count=required,
            report_status="success",
            created_at=now,
            started_at=now,
            finished_at=now,
        )
        try:
            with self.sessions.begin() as db:
                db.add(run)
                db.flush()
                for item in rows:
                    vehicle: SyntheticVehicle = item["vehicle"]
                    result = ReputationResult(
                        run_id=run_id,
                        vehicle_id=vehicle.vehicle_id,
                        series_name=vehicle.series_name,
                        vehicle_name=vehicle.vehicle_name,
                        role=vehicle.role,
                        role_position=vehicle.role_position,
                        vehicle_position=vehicle.vehicle_position,
                        platform_code=PLATFORM_CODE,
                        platform_name=PLATFORM_NAME,
                        status=item["status"],
                        metrics=item["metrics"],
                        evidence_required=item["evidence_required"],
                        error_code=item["error_code"],
                        error_message=item["error_message"],
                        collected_at=now,
                    )
                    db.add(result)
                    db.flush()
                    if item["evidence_required"]:
                        evidence = self._create_evidence(run_dir, result, item["metrics"])
                        db.add(evidence)
                db.flush()
                stored_results = db.scalars(
                    select(ReputationResult)
                    .where(ReputationResult.run_id == run_id)
                    .order_by(ReputationResult.role_position, ReputationResult.vehicle_position)
                ).all()
                evidence_by_result = {
                    item.result_id: item
                    for item in db.scalars(
                        select(ReputationEvidence).where(
                            ReputationEvidence.result_id.in_([row.id for row in stored_results])
                        )
                    ).all()
                }
                report = self._render_report(run, stored_results)
                report_path = run_dir / f"{run_number}.txt"
                report_path.write_text(report, encoding="utf-8")
                xlsx_path = run_dir / f"{run_number}.xlsx"
                self._create_xlsx(run, stored_results, evidence_by_result, xlsx_path)
                run.report_text = report
                run.report_path = str(report_path)
                run.xlsx_path = str(xlsx_path)
        except Exception:
            shutil.rmtree(run_dir, ignore_errors=True)
            raise
        if self.event_publisher:
            self.event_publisher("reputation.run.changed", run_id, status=run.status)
        return self.get_run(run_id)

    def delete_synthetic(self, run_id: str) -> dict[str, Any]:
        self._require_synthetic()
        with self.sessions.begin() as db:
            run = db.get(ReputationRun, run_id)
            if not run:
                raise DomainError(
                    "REPUTATION_RUN_NOT_FOUND", "口碑巡检运行不存在。", status_code=404
                )
            if run.source_type != "synthetic":
                raise DomainError(
                    "REPUTATION_DELETE_FORBIDDEN",
                    "这里只能删除隔离合成运行。",
                    status_code=403,
                )
            paths = [run.report_path, run.xlsx_path, run.evidence_zip_path]
            db.delete(run)
        run_dir = self.settings.reputation_dir / run_id
        shutil.rmtree(run_dir, ignore_errors=True)
        for raw in paths:
            if raw:
                Path(raw).unlink(missing_ok=True)
        return {"deleted": True}

    def get_file(self, run_id: str, kind: str) -> Path:
        with self.sessions() as db:
            run = db.get(ReputationRun, run_id)
            if not run:
                raise DomainError(
                    "REPUTATION_RUN_NOT_FOUND", "口碑巡检运行不存在。", status_code=404
                )
            raw = run.report_path if kind == "txt" else run.xlsx_path
            if not raw or not Path(raw).is_file():
                raise DomainError(
                    "REPUTATION_ARTIFACT_NOT_FOUND",
                    "口碑交付文件尚未生成。",
                    status_code=404,
                )
            return Path(raw)

    def get_evidence_file(self, evidence_id: str, kind: str) -> Path:
        with self.sessions() as db:
            evidence = db.get(ReputationEvidence, evidence_id)
            if not evidence:
                raise DomainError(
                    "REPUTATION_EVIDENCE_NOT_FOUND",
                    "口碑页面证据不存在。",
                    status_code=404,
                )
            raw = evidence.full_page_path if kind == "full" else evidence.metric_region_path
            path = Path(raw)
            if not path.is_file():
                raise DomainError(
                    "REPUTATION_EVIDENCE_FILE_MISSING",
                    "口碑页面证据文件缺失。",
                    status_code=404,
                )
            return path

    def evidence_zip(self, run_id: str) -> Path:
        with self.sessions.begin() as db:
            run = db.get(ReputationRun, run_id)
            if not run:
                raise DomainError(
                    "REPUTATION_RUN_NOT_FOUND", "口碑巡检运行不存在。", status_code=404
                )
            if run.evidence_zip_path and Path(run.evidence_zip_path).is_file():
                return Path(run.evidence_zip_path)
            results = db.scalars(
                select(ReputationResult).where(ReputationResult.run_id == run_id)
            ).all()
            result_by_id = {row.id: row for row in results}
            evidence = db.scalars(
                select(ReputationEvidence).where(
                    ReputationEvidence.result_id.in_(list(result_by_id))
                )
            ).all()
            run_dir = self.settings.reputation_dir / run_id
            zip_path = run_dir / f"{run.number}-evidence.zip"
            manifest: list[dict[str, Any]] = []
            checksums: list[str] = []
            with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED) as archive:
                for item in evidence:
                    result = result_by_id[item.result_id]
                    for label, raw_path, digest in (
                        ("full", item.full_page_path, item.full_page_sha256),
                        ("metric", item.metric_region_path, item.metric_region_sha256),
                    ):
                        name = f"{result.platform_code}/{result.vehicle_id}/{label}.png"
                        archive.write(raw_path, name)
                        checksums.append(f"{digest}  {name}")
                    manifest.append(
                        {
                            "evidence_id": item.id,
                            "result_id": result.id,
                            "vehicle_id": result.vehicle_id,
                            "platform_code": result.platform_code,
                            "full_page_sha256": item.full_page_sha256,
                            "metric_region_sha256": item.metric_region_sha256,
                        }
                    )
                archive.writestr(
                    "manifest.json",
                    json.dumps(
                        {"schema_version": "reputation-evidence-v1", "items": manifest},
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
                archive.writestr("SHA256SUMS", "\n".join(checksums) + "\n")
            run.evidence_zip_path = str(zip_path)
            return zip_path

    def get_scope(self) -> dict[str, Any]:
        with self.sessions() as db:
            draft = db.get(ReputationScopeDraft, "current")
            if not draft:
                return {
                    "initialized": False,
                    "revision": 0,
                    "vehicles": [],
                    "published_version": None,
                    "message": "尚未通过UTF-8 CSV初始化27款车型。",
                }
            data = draft.data or {}
            return {
                "initialized": True,
                "revision": draft.revision,
                "vehicles": data.get("vehicles", []),
                "published_version": self._published_version_dict(db, draft),
                "source_sha256": draft.source_sha256,
                "updated_at": draft.updated_at.isoformat(),
            }

    def initialize_scope_csv(self, path: Path) -> dict[str, Any]:
        raw = path.read_bytes()
        source_hash = hashlib.sha256(raw).hexdigest()
        rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline="")))
        expected = [
            "schema_version",
            "seed_key",
            "series_name",
            "vehicle_name",
            "role",
            "role_order",
            "platform_code",
            "platform_vehicle_id",
            "platform_url",
            "platform_display_name",
        ]
        if not rows or list(rows[0]) != expected:
            raise DomainError("REPUTATION_SCOPE_CSV_HEADER", "初始化CSV表头与固定Schema不一致。")
        if len(rows) != 27:
            raise DomainError("REPUTATION_SCOPE_COUNT", "初始化CSV必须恰好包含27款车型。")
        focus = [row for row in rows if row["role"] == "focus"]
        competitor = [row for row in rows if row["role"] == "competitor"]
        if len(focus) != 14 or len(competitor) != 13:
            raise DomainError("REPUTATION_SCOPE_ROLE_COUNT", "初始化CSV必须为14款重点和13款竞品。")
        if len({row["seed_key"] for row in rows}) != 27:
            raise DomainError("REPUTATION_SCOPE_DUPLICATE", "初始化键必须全局唯一。")
        vehicles = []
        for row in rows:
            if row["platform_code"] != PLATFORM_CODE:
                raise DomainError("REPUTATION_SCOPE_PLATFORM", "当前初始化只接受已接入平台映射。")
            try:
                role_order = int(row["role_order"])
            except ValueError as error:
                raise DomainError("REPUTATION_SCOPE_ORDER", "角色内顺序必须是整数。") from error
            vehicles.append(
                {
                    "id": row["seed_key"],
                    "series_name": row["series_name"],
                    "vehicle_name": row["vehicle_name"],
                    "role": row["role"],
                    "role_order": role_order,
                    "enabled": True,
                    "mappings": {
                        PLATFORM_CODE: {
                            "platform_vehicle_id": row["platform_vehicle_id"],
                            "platform_url": row["platform_url"],
                            "platform_display_name": row["platform_display_name"],
                            "validation_status": "unverified",
                        }
                    },
                }
            )
        for group, expected_count in ((focus, 14), (competitor, 13)):
            positions = sorted(int(row["role_order"]) for row in group)
            if positions != list(range(1, expected_count + 1)):
                raise DomainError("REPUTATION_SCOPE_ORDER", "角色内顺序必须从1连续编号。")
        with self.sessions.begin() as db:
            existing = db.get(ReputationScopeDraft, "current")
            if existing:
                if existing.source_sha256 == source_hash:
                    return self.get_scope()
                raise DomainError("REPUTATION_SCOPE_EXISTS", "口碑范围已经初始化，不能覆盖导入。")
            db.add(
                ReputationScopeDraft(
                    id="current",
                    revision=1,
                    data={"schema_version": rows[0]["schema_version"], "vehicles": vehicles},
                    source_sha256=source_hash,
                )
            )
        return self.get_scope()

    def preview_mappings(self, value: MappingPasteRequest) -> dict[str, Any]:
        scope = self.get_scope()
        if not scope["initialized"]:
            raise DomainError("REPUTATION_SCOPE_UNINITIALIZED", "请先初始化口碑车型范围。")
        if value.revision != scope["revision"]:
            raise DomainError(
                "REPUTATION_SCOPE_CONFLICT",
                "范围草稿已经变化，请刷新后重试。",
                status_code=409,
            )
        if value.platform_code != PLATFORM_CODE:
            raise DomainError(
                "REPUTATION_SCOPE_PLATFORM",
                "当前阶段只接受已接入平台的车型映射。",
            )
        vehicle_ids = {row["id"] for row in scope["vehicles"]}
        errors: list[dict[str, str]] = []
        seen_vehicle: set[str] = set()
        seen_platform: set[str] = set()
        for index, row in enumerate(value.rows, start=1):
            if row.vehicle_id not in vehicle_ids:
                errors.append({"row": str(index), "reason": "内部车型ID不存在"})
            if row.vehicle_id in seen_vehicle:
                errors.append({"row": str(index), "reason": "内部车型ID重复"})
            if row.platform_vehicle_id in seen_platform:
                errors.append({"row": str(index), "reason": "平台车型ID重复"})
            if not row.platform_url.startswith(("https://", "http://")):
                errors.append({"row": str(index), "reason": "页面URL格式错误"})
            if not row.platform_vehicle_id.strip():
                errors.append({"row": str(index), "reason": "平台车型ID不能为空"})
            if not row.platform_display_name.strip():
                errors.append({"row": str(index), "reason": "平台展示名不能为空"})
            seen_vehicle.add(row.vehicle_id)
            seen_platform.add(row.platform_vehicle_id)
        payload = value.model_dump()
        return {
            "valid": not errors,
            "errors": errors,
            "changed_count": len(value.rows),
            "unchanged_count": len(vehicle_ids - seen_vehicle),
            "input_hash": _text_hash(payload),
            "revision": value.revision,
        }

    def save_mappings(self, value: MappingPasteRequest) -> dict[str, Any]:
        preview = self.preview_mappings(value)
        if not preview["valid"]:
            raise DomainError(
                "REPUTATION_MAPPING_INVALID",
                "批量映射存在错误，本次没有保存任何行。",
                details=preview["errors"],
            )
        with self.sessions.begin() as db:
            draft = db.get(ReputationScopeDraft, "current")
            if not draft or draft.revision != value.revision:
                raise DomainError(
                    "REPUTATION_SCOPE_CONFLICT",
                    "范围草稿已经变化，请刷新后重试。",
                    status_code=409,
                )
            data = json.loads(json.dumps(draft.data, ensure_ascii=False))
            by_id = {row["id"]: row for row in data["vehicles"]}
            for row in value.rows:
                by_id[row.vehicle_id].setdefault("mappings", {})[value.platform_code] = {
                    "platform_vehicle_id": row.platform_vehicle_id,
                    "platform_url": row.platform_url,
                    "platform_display_name": row.platform_display_name,
                    "validation_status": "unverified",
                }
            draft.data = data
            draft.revision += 1
        return self.get_scope()

    def publish_preview(self) -> dict[str, Any]:
        scope = self.get_scope()
        if not scope["initialized"]:
            raise DomainError("REPUTATION_SCOPE_UNINITIALIZED", "请先初始化口碑车型范围。")
        vehicles = scope["vehicles"]
        verified = sum(
            1
            for vehicle in vehicles
            if vehicle.get("mappings", {}).get(PLATFORM_CODE, {}).get("validation_status")
            == "verified"
        )
        return {
            "revision": scope["revision"],
            "initial_publish": scope["published_version"] is None,
            "vehicle_count": len(vehicles),
            "focus_count": sum(row["role"] == "focus" for row in vehicles),
            "competitor_count": sum(row["role"] == "competitor" for row in vehicles),
            "verified_mapping_count": verified,
            "expected_mapping_count": len(vehicles),
            "can_publish": verified == len(vehicles),
            "warning": None
            if verified == len(vehicles)
            else "真实页面验证尚未全部完成，当前不会开放发布。",
        }

    def publish_scope(self, value: ScopePublishRequest) -> dict[str, Any]:
        preview = self.publish_preview()
        if value.revision != preview["revision"]:
            raise DomainError(
                "REPUTATION_SCOPE_CONFLICT",
                "范围草稿已经变化，请重新预览。",
                status_code=409,
            )
        if not preview["can_publish"]:
            raise DomainError("REPUTATION_SCOPE_NOT_VERIFIED", "全部映射验证通过后才能发布。")
        if preview["initial_publish"] and not value.initial_review_acknowledged:
            raise DomainError("REPUTATION_INITIAL_REVIEW_REQUIRED", "请先确认首发全量复核。")
        with self.sessions.begin() as db:
            draft = db.get(ReputationScopeDraft, "current")
            if not draft or draft.revision != value.revision:
                raise DomainError(
                    "REPUTATION_SCOPE_CONFLICT",
                    "范围草稿已经变化，请重新预览。",
                    status_code=409,
                )
            next_version = (db.scalar(select(func.max(ReputationScopeVersion.version))) or 0) + 1
            version = ReputationScopeVersion(
                version=next_version,
                snapshot=json.loads(json.dumps(draft.data, ensure_ascii=False)),
                source_revision=draft.revision,
            )
            db.add(version)
            db.flush()
            draft.published_version_id = version.id
        return self.get_scope()

    def _published_version_dict(
        self, db: Session, draft: ReputationScopeDraft
    ) -> dict[str, Any] | None:
        if not draft.published_version_id:
            return None
        version = db.get(ReputationScopeVersion, draft.published_version_id)
        return (
            {
                "id": version.id,
                "version": version.version,
                "published_at": version.published_at.isoformat(),
            }
            if version
            else None
        )

    def _create_evidence(
        self, run_dir: Path, result: ReputationResult, metrics: dict[str, Any]
    ) -> ReputationEvidence:
        evidence_id = uuid7()
        evidence_dir = run_dir / "evidence" / result.vehicle_id
        evidence_dir.mkdir(parents=True, exist_ok=True)
        full_path = evidence_dir / "full.png"
        metric_path = evidence_dir / "metric.png"
        self._draw_fixture(full_path, result, metrics, size=(1200, 720), compact=False)
        self._draw_fixture(metric_path, result, metrics, size=(980, 220), compact=True)
        return ReputationEvidence(
            id=evidence_id,
            result_id=result.id,
            full_page_path=str(full_path),
            metric_region_path=str(metric_path),
            full_page_sha256=_sha256(full_path),
            metric_region_sha256=_sha256(metric_path),
            width=1200,
            height=720,
        )

    @staticmethod
    def _draw_fixture(
        path: Path,
        result: ReputationResult,
        metrics: dict[str, Any],
        *,
        size: tuple[int, int],
        compact: bool,
    ) -> None:
        image = Image.new("RGB", size, "#F8FAFC")
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle(
            (28, 24, size[0] - 28, size[1] - 24), radius=22, fill="#FFFFFF", outline="#CBD5E1", width=2
        )
        draw.rectangle((28, 24, size[0] - 28, 82), fill="#1E3A8A")
        draw.text((52, 44), f"SYNTHETIC EVIDENCE / {result.vehicle_id}", fill="white")
        labels = (("SCORE", "score"), ("RANK", "rank"), ("VOLUME", "volume"))
        top = 112 if compact else 180
        box_height = 76 if compact else 150
        gap = 20
        width = (size[0] - 104 - gap * 2) // 3
        for index, (label, key) in enumerate(labels):
            left = 52 + index * (width + gap)
            draw.rounded_rectangle(
                (left, top, left + width, top + box_height),
                radius=16,
                fill="#EFF6FF",
                outline="#BFDBFE",
                width=2,
            )
            value = metrics[key].get("raw") or metrics[key].get("comparison_status") or "-"
            draw.text((left + 18, top + 18), label, fill="#475569")
            draw.text((left + 18, top + 44), str(value), fill="#0F172A")
        if not compact:
            draw.text((52, 112), "Full-page synthetic fixture. No platform request was issued.", fill="#64748B")
            draw.text((52, size[1] - 64), "ThreadSnap reputation inspection acceptance fixture", fill="#64748B")
        image.save(path, format="PNG", optimize=False)

    def _render_report(self, run: ReputationRun, results: list[ReputationResult]) -> str:
        title = f"{run.planned_date}口碑分及排名变动如下："
        lines = [title, "", f"【{PLATFORM_NAME}】"]
        if run.run_type == "baseline_initialization":
            lines.extend(["首次基线初始化，无前日变化可比较。", f"全量页面证据：{run.complete_evidence_count}/{run.required_evidence_count}"])
            return "\n".join(lines) + "\n"
        changed_count = 0
        anomalies: list[str] = []
        for result in results:
            changes: list[str] = []
            for key, name in (("score", "口碑分"), ("rank", "排名"), ("volume", "口碑量")):
                metric = result.metrics[key]
                if metric.get("direction") in {"up", "down"}:
                    direction = "上升" if metric["direction"] == "up" else "下降"
                    changes.append(
                        f"{name}{metric['raw']}，较昨日{direction}{str(metric['delta']).lstrip('+-')}"
                    )
            if changes:
                changed_count += 1
                lines.append(f"{changed_count}. 【{result.vehicle_name}】" + "；".join(changes) + "。")
            if result.status != "success" or any(
                item.get("comparison_status") not in {"comparable"}
                for item in result.metrics.values()
            ):
                states = sorted(
                    {
                        item.get("comparison_status", "unknown")
                        for item in result.metrics.values()
                        if item.get("comparison_status") != "comparable"
                    }
                )
                anomalies.append(
                    f"- {result.vehicle_name}：{result.error_message or '、'.join(states)}"
                )
        if not changed_count:
            lines.append("今日无口碑指标变化。")
        if anomalies:
            lines.extend(["", "异常与缺失：", *anomalies])
        if run.run_type == "month_end":
            lines.extend(["", "月末巡检：已执行当前范围全量页面证据。"])
        return "\n".join(lines) + "\n"

    def _create_xlsx(
        self,
        run: ReputationRun,
        results: list[ReputationResult],
        evidence_by_result: dict[str, ReputationEvidence],
        path: Path,
    ) -> None:
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "口碑巡检"
        headers = ["日期", "角色", "车系", "车型", "口碑分", "排名", "口碑量", "备注"]
        sheet.append(headers)
        for cell in sheet[1]:
            cell.fill = HEADER_FILL
            cell.font = Font(bold=True)
            cell.alignment = Alignment(horizontal="center", vertical="center")
        for row_index, result in enumerate(results, start=2):
            values = [
                run.planned_date,
                "重点车型" if result.role == "focus" else "竞品车型",
                result.series_name,
                result.vehicle_name,
                result.metrics["score"].get("raw") or "—",
                result.metrics["rank"].get("raw") or "—",
                result.metrics["volume"].get("raw") or "—",
                "",
            ]
            sheet.append(values)
            for column, metric_name in ((5, "score"), (6, "rank"), (7, "volume")):
                tone = result.metrics[metric_name].get("tone")
                sheet.cell(row_index, column).fill = (
                    GREEN_FILL if tone == "positive" else RED_FILL if tone == "negative" else NEUTRAL_FILL
                )
                sheet.cell(row_index, column).alignment = Alignment(horizontal="center")
            evidence = evidence_by_result.get(result.id)
            if evidence:
                preview = WorksheetImage(evidence.metric_region_path)
                preview.width = 294
                preview.height = 66
                sheet.add_image(preview, f"H{row_index}")
                sheet.row_dimensions[row_index].height = 52
        widths = [13, 12, 18, 22, 12, 12, 14, 44]
        for index, width in enumerate(widths, start=1):
            sheet.column_dimensions[get_column_letter(index)].width = width
        sheet.freeze_panes = "E2"
        sheet.auto_filter.ref = f"A1:H{len(results) + 1}"
        workbook.save(path)

    @staticmethod
    def _run_dict(run: ReputationRun) -> dict[str, Any]:
        return {
            "id": run.id,
            "number": run.number,
            "source_type": run.source_type,
            "scenario_id": run.scenario_id,
            "run_type": run.run_type,
            "planned_date": run.planned_date,
            "status": run.status,
            "platform_codes": run.platform_codes,
            "planned_count": run.planned_count,
            "completed_count": run.completed_count,
            "failed_count": run.failed_count,
            "required_evidence_count": run.required_evidence_count,
            "complete_evidence_count": run.complete_evidence_count,
            "report_status": run.report_status,
            "report_text": run.report_text,
            "created_at": run.created_at.isoformat(),
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        }

    @staticmethod
    def _result_dict(
        result: ReputationResult,
        evidence: ReputationEvidence | None,
        prefix: str,
    ) -> dict[str, Any]:
        return {
            "id": result.id,
            "vehicle_id": result.vehicle_id,
            "series_name": result.series_name,
            "vehicle_name": result.vehicle_name,
            "role": result.role,
            "role_position": result.role_position,
            "vehicle_position": result.vehicle_position,
            "platform_code": result.platform_code,
            "platform_name": result.platform_name,
            "status": result.status,
            "metrics": result.metrics,
            "evidence_required": result.evidence_required,
            "error_code": result.error_code,
            "error_message": result.error_message,
            "collected_at": result.collected_at.isoformat(),
            "evidence": {
                "id": evidence.id,
                "full_page_url": f"{prefix}/reputation/evidence/{evidence.id}/full",
                "metric_region_url": f"{prefix}/reputation/evidence/{evidence.id}/metric",
                "full_page_sha256": evidence.full_page_sha256,
                "metric_region_sha256": evidence.metric_region_sha256,
            }
            if evidence
            else None,
        }
