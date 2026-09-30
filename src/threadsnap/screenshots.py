"""圈子页面原始证据、负面框选成果和版本生命周期。"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
import zipfile
from collections import OrderedDict
from contextlib import nullcontext
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from .config import Settings
from .errors import DomainError
from .ids import uuid7
from .models import (
    CirclePageEvidence,
    CirclePageEvidenceItem,
    CircleTask,
    ExtractionRun,
    PostSnapshot,
    ScreenshotArtifactContribution,
    ScreenshotArtifactGroup,
    ScreenshotArtifactItem,
    ScreenshotArtifactTile,
    ScreenshotArtifactVersion,
    utc_now,
)
from .services import related_run_ids

TERMINAL_TASK_STATUSES = {"success", "partial_success", "failed"}
RENDERER_VERSION = "v8-skip-deleted-posts"


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid7()}.tmp")
    temporary.write_bytes(value)
    os.replace(temporary, path)


def _zip_member(name: str) -> zipfile.ZipInfo:
    """冻结 ZIP 元信息，避免下载时间、PNG mtime 或操作系统改变包的字节。"""

    item = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    item.compress_type = zipfile.ZIP_STORED
    item.create_system = 3
    item.external_attr = 0o100644 << 16
    return item


def _render_card_box(source: Image.Image, item: Any, evidence: Any) -> tuple[int, int, int, int]:
    """使用证据绑定几何，图片颜色不参与任何卡片寻址。"""

    left, top = int(item.x), int(item.y)
    right, bottom = left + int(item.width), top + int(item.height)
    if getattr(evidence, "adapter_version", "") == "autohome-club-v10-scrapling-page-evidence":
        # 旧 v10 存的是占父栏 96% 的 li，只保留已确认的固定水平边距换算。
        gutter = max(1, int(int(item.width) * 0.02 / 0.96))
        left, right = max(0, left - gutter), min(source.width, right + gutter)
    return left, top, right, bottom


@lru_cache(maxsize=8)
def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in (
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    ):
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


class ScreenshotService:
    """持久化同步页面证据，并按当前有效结论生成不可变成果版本。"""

    def __init__(self, factory: sessionmaker[Session], settings: Settings):
        self.factory = factory
        self.settings = settings
        self._rebuild_lock = threading.RLock()

    @staticmethod
    def _root_run_id(db: Session, run_id: str) -> str:
        run = db.get(ExtractionRun, run_id)
        if not run:
            return run_id
        while run.related_run_id:
            parent = db.get(ExtractionRun, run.related_run_id)
            if not parent:
                break
            run = parent
        return run.id

    def capture_callback(self, task_id: str):
        """返回采集器页面证据回调；每页先持久化再继续详情提取。"""

        def persist(payload: dict[str, Any]) -> None:
            self.persist_page(task_id, payload)

        persist.load = lambda page_number: self.load_page(task_id, page_number)  # type: ignore[attr-defined]
        return persist

    def register_task(self, task_id: str) -> None:
        """在打开平台页面前建立成果组，使零结果和页面级失败也可见。"""

        with self.factory.begin() as db:
            task = db.get(CircleTask, task_id)
            if not task:
                return
            group = self._get_or_create_group(db, task)
            contribution = db.scalar(
                select(ScreenshotArtifactContribution).where(
                    ScreenshotArtifactContribution.group_id == group.id,
                    ScreenshotArtifactContribution.circle_task_id == task.id,
                )
            )
            if not contribution:
                db.add(
                    ScreenshotArtifactContribution(
                        group_id=group.id,
                        run_id=task.run_id,
                        circle_task_id=task.id,
                    )
                )
            group.status = "evidence_pending"
            group.dirty = True

    def load_page(self, task_id: str, page_number: int) -> dict[str, Any] | None:
        """重启续跑复用哈希一致的冻结清单，不再次访问同一历史页面。"""

        with self.factory() as db:
            evidence = db.scalar(
                select(CirclePageEvidence).where(
                    CirclePageEvidence.circle_task_id == task_id,
                    CirclePageEvidence.page_number == page_number,
                )
            )
            if not evidence:
                return None
            manifest_path = Path(evidence.manifest_path)
            image_path = Path(evidence.screenshot_path)
            if (
                not manifest_path.is_file()
                or not image_path.is_file()
                or _sha256_file(manifest_path) != evidence.manifest_sha256
                or _sha256_file(image_path) != evidence.screenshot_sha256
            ):
                raise DomainError(
                    "PAGE_EVIDENCE_CORRUPTED",
                    "已保存的原始页面证据文件缺失或哈希异常。",
                    status_code=500,
                )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            return {**manifest, "adapter_version": evidence.adapter_version, "persisted": True}

    def persist_page(self, task_id: str, payload: dict[str, Any]) -> None:
        page_number = int(payload["page_number"])
        with self.factory.begin() as db:
            task = db.get(CircleTask, task_id)
            if not task:
                return
            existing = db.scalar(
                select(CirclePageEvidence).where(
                    CirclePageEvidence.circle_task_id == task_id,
                    CirclePageEvidence.page_number == page_number,
                )
            )
            if existing:
                return
            evidence_id = uuid7()
            root = self.settings.screenshot_evidence_dir / task.run_id / task.id
            image_path = root / f"page-{page_number:04d}.png"
            manifest_path = root / f"page-{page_number:04d}.json"
            image_bytes = bytes(payload["screenshot"])
            list_schema = payload.get("list_schema_version", "circle-page-v1")
            manifest = {
                "schema": "threadsnap.circle-page-evidence.v1",
                "captured_at": payload["captured_at"],
                "exact_url": payload["exact_url"],
                "page_number": page_number,
                "viewport": payload["viewport"],
                "document": payload["document"],
                "browser_version": payload["browser_version"],
                "adapter_version": payload["adapter_version"],
                "list_schema_version": list_schema,
                "rows": payload["rows"],
            }
            for optional_key in ("total_count", "page_count", "capture_geometry"):
                if optional_key in payload:
                    manifest[optional_key] = payload[optional_key]
            manifest_bytes = json.dumps(
                manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            _atomic_write(image_path, image_bytes)
            _atomic_write(manifest_path, manifest_bytes)
            try:
                with nullcontext():
                    task = db.get(CircleTask, task_id)
                    if not task:
                        raise RuntimeError("task disappeared")
                    evidence = CirclePageEvidence(
                        id=evidence_id,
                        run_id=task.run_id,
                        circle_task_id=task.id,
                        page_number=page_number,
                        exact_url=str(payload["exact_url"]),
                        status="ready",
                        adapter_version=str(payload["adapter_version"]),
                        browser_version=str(payload["browser_version"]),
                        list_schema_version=list_schema,
                        device_scale_factor=int(payload["viewport"].get("device_scale_factor", 1)),
                        viewport_width=int(payload["viewport"]["width"]),
                        viewport_height=int(payload["viewport"]["height"]),
                        document_width=int(payload["document"]["width"]),
                        document_height=int(payload["document"]["height"]),
                        screenshot_path=str(image_path.resolve()),
                        screenshot_sha256=_sha256_bytes(image_bytes),
                        manifest_path=str(manifest_path.resolve()),
                        manifest_sha256=_sha256_bytes(manifest_bytes),
                        captured_at=utc_now(),
                    )
                    db.add(evidence)
                    for row in payload["rows"]:
                        db.add(
                            CirclePageEvidenceItem(
                                evidence_id=evidence.id,
                                circle_task_id=task.id,
                                platform_post_id=str(row["post_id"]),
                                url=str(row["url"]),
                                source_position=int(row["source_position"]),
                                x=max(0, round(float(row["rect"]["x"]))),
                                y=max(0, round(float(row["rect"]["y"]))),
                                width=max(1, round(float(row["rect"]["width"]))),
                                height=max(1, round(float(row["rect"]["height"]))),
                                text_sha256=_sha256_bytes(str(row.get("text") or "").encode()),
                                image_count=int(row.get("image_count") or 0),
                            )
                        )
                    group = self._get_or_create_group(db, task)
                    contribution = db.scalar(
                        select(ScreenshotArtifactContribution).where(
                            ScreenshotArtifactContribution.group_id == group.id,
                            ScreenshotArtifactContribution.circle_task_id == task.id,
                        )
                    )
                    if not contribution:
                        db.add(
                            ScreenshotArtifactContribution(
                                group_id=group.id,
                                run_id=task.run_id,
                                circle_task_id=task.id,
                            )
                        )
                    group.status = "evidence_running"
                    group.dirty = True
            except Exception:
                image_path.unlink(missing_ok=True)
                manifest_path.unlink(missing_ok=True)
                raise

    def _get_or_create_group(self, db: Session, task: CircleTask) -> ScreenshotArtifactGroup:
        root_id = self._root_run_id(db, task.run_id)
        group = db.scalar(
            select(ScreenshotArtifactGroup).where(
                ScreenshotArtifactGroup.chain_root_run_id == root_id,
                ScreenshotArtifactGroup.platform_code == task.platform_code,
                ScreenshotArtifactGroup.external_id == task.external_id,
                ScreenshotArtifactGroup.section == task.section,
                ScreenshotArtifactGroup.list_order == task.list_order,
            )
        )
        if group:
            return group
        group = ScreenshotArtifactGroup(
            chain_root_run_id=root_id,
            platform_code=task.platform_code,
            external_id=task.external_id,
            circle_name=task.circle_name,
            section=task.section,
            list_order=task.list_order,
        )
        db.add(group)
        db.flush()
        return group

    def link_post(self, db: Session, task_id: str, post: PostSnapshot) -> None:
        """将详情快照关联回同一冻结页面中的卡片。"""

        item = db.scalar(
            select(CirclePageEvidenceItem)
            .where(
                CirclePageEvidenceItem.circle_task_id == task_id,
                CirclePageEvidenceItem.platform_post_id == post.platform_post_id,
            )
            .order_by(CirclePageEvidenceItem.source_position)
            .limit(1)
        )
        if item:
            item.post_snapshot_id = post.id

    def mark_task_complete(self, task_id: str) -> None:
        with self.factory.begin() as db:
            contribution = db.scalar(
                select(ScreenshotArtifactContribution).where(
                    ScreenshotArtifactContribution.circle_task_id == task_id
                )
            )
            if contribution:
                group = db.get(ScreenshotArtifactGroup, contribution.group_id)
                if group:
                    group.dirty = True
                    group.status = "waiting_for_sentiment"

    def process_once(self) -> bool:
        """生成一个已具备完整结论的脏成果组。"""

        with self.factory() as db:
            group_ids = list(
                db.scalars(
                    select(ScreenshotArtifactGroup.id)
                    .where(ScreenshotArtifactGroup.dirty.is_(True))
                    .order_by(ScreenshotArtifactGroup.updated_at)
                )
            )
        for group_id in group_ids:
            if self.rebuild(group_id):
                return True
        return self._refresh_one_stale_group()

    def _refresh_one_stale_group(self) -> bool:
        """检测成果生成后的舆情结论更新并创建新版本。"""

        stale_id: str | None = None
        with self.factory() as db:
            groups = list(
                db.scalars(
                    select(ScreenshotArtifactGroup)
                    .where(
                        ScreenshotArtifactGroup.status == "ready",
                        ScreenshotArtifactGroup.dirty.is_(False),
                    )
                    .order_by(ScreenshotArtifactGroup.updated_at)
                )
            )
            for group in groups:
                version = db.scalar(
                    select(ScreenshotArtifactVersion).where(
                        ScreenshotArtifactVersion.group_id == group.id,
                        ScreenshotArtifactVersion.version == group.current_version,
                    )
                )
                if not version:
                    continue
                task_ids = list(
                    db.scalars(
                        select(ScreenshotArtifactContribution.circle_task_id).where(
                            ScreenshotArtifactContribution.group_id == group.id
                        )
                    )
                )
                changed = (
                    db.scalar(
                        select(PostSnapshot.id)
                        .join(
                            CirclePageEvidenceItem,
                            CirclePageEvidenceItem.post_snapshot_id == PostSnapshot.id,
                        )
                        .where(
                            CirclePageEvidenceItem.circle_task_id.in_(task_ids),
                            PostSnapshot.sentiment_updated_at > version.created_at,
                        )
                        .limit(1)
                    )
                    if task_ids
                    else None
                )
                if changed:
                    stale_id = group.id
                    break
        return self.rebuild(stale_id, reason="sentiment_changed") if stale_id else False

    def rebuild(self, group_id: str, reason: str = "automatic") -> bool:
        # 同一服务实例的后台与手动重建串行，避免同时占用或清理同一个版本目录。
        with self._rebuild_lock:
            return self._rebuild(group_id, reason)

    def _rebuild(self, group_id: str, reason: str) -> bool:
        with self.factory.begin() as db:
            group = db.get(ScreenshotArtifactGroup, group_id)
            if not group:
                return False
            contributions = list(
                db.scalars(
                    select(ScreenshotArtifactContribution)
                    .where(ScreenshotArtifactContribution.group_id == group.id)
                    .order_by(ScreenshotArtifactContribution.created_at)
                )
            )
            tasks = [db.get(CircleTask, item.circle_task_id) for item in contributions]
            tasks = [task for task in tasks if task is not None]
            task_ai_enabled = {
                task.id: bool((task.config_snapshot or {}).get("ai_analysis_enabled", True))
                for task in tasks
            }
            if any(task.status not in TERMINAL_TASK_STATUSES for task in tasks):
                with nullcontext():
                    group.status = "evidence_running"
                return False
            rows = (
                list(
                    db.execute(
                        select(CirclePageEvidenceItem, PostSnapshot, CirclePageEvidence)
                        .join(
                            PostSnapshot,
                            PostSnapshot.id == CirclePageEvidenceItem.post_snapshot_id,
                        )
                        .join(
                            CirclePageEvidence,
                            CirclePageEvidence.id == CirclePageEvidenceItem.evidence_id,
                        )
                        .where(
                            CirclePageEvidenceItem.circle_task_id.in_(
                                [item.circle_task_id for item in contributions]
                            )
                        )
                        .order_by(
                            CirclePageEvidence.captured_at,
                            CirclePageEvidenceItem.source_position,
                        )
                    )
                )
                if contributions
                else []
            )
            deduped: OrderedDict[str, tuple[Any, Any, Any]] = OrderedDict()
            for item, post, evidence in rows:
                deduped.setdefault(post.platform_post_id, (item, post, evidence))
            selected = list(deduped.values())
            effective_sentiments = [
                "not_analyzed"
                if post.is_deleted
                else post.sentiment_result
                if post.sentiment_result is not None
                else ("not_analyzed" if not task_ai_enabled.get(item.circle_task_id, True) else None)
                for item, post, _evidence in selected
            ]
            if any(sentiment is None for sentiment in effective_sentiments):
                with nullcontext():
                    group.status = "waiting_for_sentiment"
                    group.error_message = None
                return False
            if not selected and tasks and all(task.status == "failed" for task in tasks):
                with nullcontext():
                    group.status = "failed"
                    group.dirty = False
                    group.error_message = "圈子任务没有取得可生成成果的有效页面条目。"
                return True
            run_numbers = {
                evidence.run_id: (
                    run.number
                    if (run := db.get(ExtractionRun, evidence.run_id))
                    else evidence.run_id
                )
                for _item, _post, evidence in selected
            }
            inputs = [
                {
                    "post_id": post.id,
                    "platform_post_id": post.platform_post_id,
                    "sentiment": effective_sentiments[index],
                    "sentiment_updated_at": (
                        post.sentiment_updated_at.isoformat() if post.sentiment_updated_at else None
                    ),
                    "evidence_id": evidence.id,
                    "evidence_sha256": evidence.screenshot_sha256,
                    "evidence_manifest_sha256": evidence.manifest_sha256,
                    "geometry_schema": evidence.list_schema_version,
                    "evidence_run_id": evidence.run_id,
                    "evidence_page_number": evidence.page_number,
                    "evidence_adapter_version": evidence.adapter_version,
                    "run_number": run_numbers[evidence.run_id],
                    "captured_at": evidence.captured_at.isoformat(),
                    "rect": [item.x, item.y, item.width, item.height],
                }
                for index, (item, post, evidence) in enumerate(selected)
            ]
            input_sha = _sha256_bytes(
                json.dumps(
                    {"renderer_version": RENDERER_VERSION, "items": inputs},
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            )
            latest = db.scalar(
                select(ScreenshotArtifactVersion)
                .where(ScreenshotArtifactVersion.group_id == group.id)
                .order_by(ScreenshotArtifactVersion.version.desc())
                .limit(1)
            )
            if latest and latest.input_sha256 == input_sha:
                with nullcontext():
                    group.status = "empty" if not selected else "ready"
                    group.dirty = False
                return True
            if latest and any(
                evidence.adapter_version in {
                    "dongchedi-dynamic-v4",
                    "dongchedi-dynamic-v7-scrapling",
                }
                for _item, _post, evidence in selected
            ):
                group.dirty = False
                group.status = "ready"
                group.error_message = "旧版页面存在截图排版偏移，保留已发布版本；新采集使用同宽截图。"
                return True
            version_number = (latest.version if latest else 0) + 1
            group_snapshot = {
                "id": group.id,
                "circle_name": group.circle_name,
                "external_id": group.external_id,
                "list_order": group.list_order,
            }
            group.status = "rendering"
        output_existed = (
            self.settings.screenshot_artifact_dir / group_snapshot["id"] / f"v{version_number:04d}"
        ).exists()
        try:
            rendered = self._render(group_snapshot, version_number, selected, inputs)
            with self.factory.begin() as db:
                group = db.get(ScreenshotArtifactGroup, group_id)
                if not group:
                    return False
                version = ScreenshotArtifactVersion(
                    group_id=group.id,
                    version=version_number,
                    status="ready",
                    reason=reason,
                    input_sha256=input_sha,
                    item_count=len(selected),
                    negative_count=sum(item["sentiment"] == "negative" for item in inputs),
                    tiles=rendered["tiles"],
                    items=rendered["items"],
                    package_path=rendered["package_path"],
                    package_sha256=rendered["package_sha256"],
                )
                db.add(version)
                db.flush()
                for tile in rendered["tiles"]:
                    db.add(
                        ScreenshotArtifactTile(
                            version_id=version.id,
                            tile_index=int(tile["index"]),
                            file_path=str(tile["path"]),
                            file_sha256=str(tile["sha256"]),
                            width=int(tile["width"]),
                            height=int(tile["height"]),
                        )
                    )
                for item in rendered["items"]:
                    db.add(
                        ScreenshotArtifactItem(
                            version_id=version.id,
                            post_snapshot_id=item["post_id"],
                            platform_post_id=item["platform_post_id"],
                            title=item.get("title"),
                            sentiment_result=item["sentiment_result"],
                            contribution_run_number=item["run_number"],
                            captured_at=datetime.fromisoformat(item["captured_at"]),
                            tile_index=int(item["tile_index"]),
                            y=int(item["y"]),
                            height=int(item["height"]),
                        )
                    )
                group.current_version = version_number
                group.item_count = version.item_count
                group.negative_count = version.negative_count
                group.status = "empty" if not selected else "ready"
                group.dirty = False
                group.error_message = None
            return True
        except Exception as exc:
            if not output_existed:
                shutil.rmtree(
                    self.settings.screenshot_artifact_dir
                    / group_snapshot["id"]
                    / f"v{version_number:04d}",
                    ignore_errors=True,
                )
            with self.factory.begin() as db:
                group = db.get(ScreenshotArtifactGroup, group_id)
                if group:
                    group.status = "failed"
                    group.dirty = False
                    group.error_message = f"{type(exc).__name__}: {exc}"
            return True

    def _render(
        self,
        group: dict[str, Any],
        version: int,
        selected: list[tuple[Any, Any, Any]],
        inputs: list[dict[str, Any]],
    ) -> dict[str, Any]:
        output_dir = self.settings.screenshot_artifact_dir / group["id"] / f"v{version:04d}"
        output_dir.mkdir(parents=True, exist_ok=False)

        # 一个成果 tile 对应一张实际参与去重结果的原始页面证据。页面顺序仍由
        # selected 的既有顺序决定，帖子去重、判定和框选边界逻辑均不改变。
        page_specs: OrderedDict[
            str,
            tuple[Any, list[tuple[int, Any, Any]]],
        ] = OrderedDict()
        for selected_index, (item, post, evidence) in enumerate(selected):
            evidence_key = str(getattr(evidence, "id", None) or evidence.screenshot_path)
            page = page_specs.get(evidence_key)
            if page is None:
                page = (evidence, [])
                page_specs[evidence_key] = page
            page[1].append((selected_index, item, post))

        tiles: list[dict[str, Any]] = []
        artifact_items: list[dict[str, Any]] = []
        for tile_index, (evidence, page_cards) in enumerate(page_specs.values()):
            source_path = Path(evidence.screenshot_path)
            actual_sha256 = _sha256_file(source_path)
            expected_sha256 = getattr(evidence, "screenshot_sha256", actual_sha256)
            if actual_sha256 != expected_sha256:
                raise RuntimeError(f"原始页面证据校验失败：{source_path}")
            with Image.open(source_path) as source:
                canvas = source.convert("RGB")
                draw = ImageDraw.Draw(canvas)
                has_negative = False
                for selected_index, item, post in page_cards:
                    left, top, right, bottom = _render_card_box(source, item, evidence)
                    effective_sentiment = inputs[selected_index].get(
                        "sentiment",
                        getattr(post, "sentiment_result", None),
                    )
                    if effective_sentiment == "negative":
                        has_negative = True
                        draw.rectangle(
                            (
                                left + 2,
                                top + 2,
                                max(left + 2, right - 3),
                                max(top + 2, bottom - 3),
                            ),
                            outline="#ef4444",
                            width=5,
                        )
                    artifact_items.append(
                        {
                            "post_id": post.id,
                            "platform_post_id": post.platform_post_id,
                            "title": post.title,
                            "sentiment_result": effective_sentiment,
                            "run_number": inputs[selected_index]["run_number"],
                            "captured_at": inputs[selected_index]["captured_at"],
                            "tile_index": tile_index,
                            "y": top,
                            "height": bottom - top,
                            "source_rect": [left, top, right - left, bottom - top],
                            "original_rect": [item.x, item.y, item.width, item.height],
                            "geometry_authority": "recorded-dom",
                            "source_manifest_sha256": getattr(evidence, "manifest_sha256", None),
                        }
                    )
            tile_path = output_dir / f"tile-{tile_index + 1:04d}.png"
            if has_negative:
                canvas.save(tile_path, format="PNG", optimize=True)
            else:
                # 两条独立路径共享只读原图；删除任一路径不会使另一份证据失效。
                # 跨文件系统或不支持硬链接时退回字节复制，不改变图片与渲染合同。
                try:
                    os.link(source_path, tile_path)
                except OSError:
                    shutil.copyfile(source_path, tile_path)
            tiles.append(
                {
                    "index": tile_index,
                    "path": str(tile_path.resolve()),
                    "sha256": _sha256_file(tile_path),
                    "width": canvas.width,
                    "height": canvas.height,
                    "source_evidence_id": getattr(evidence, "id", None),
                    "source_sha256": getattr(evidence, "screenshot_sha256", None),
                    "source_run_id": getattr(evidence, "run_id", None),
                    "source_page_number": getattr(evidence, "page_number", None),
                    "captured_at": (
                        evidence.captured_at.isoformat()
                        if getattr(evidence, "captured_at", None)
                        else None
                    ),
                }
            )
            canvas.close()

        # 兼容没有原始页面证据的历史“成功但 0 条”任务；真实证据一旦存在，
        # 成果始终使用完整原图，不进入此占位分支。
        if not tiles:
            canvas = Image.new("RGB", (1440, 240), "#ffffff")
            draw = ImageDraw.Draw(canvas)
            draw.text((20, 100), "本次圈子页面有效条目为 0。", fill="#475569", font=_font(20))
            tile_path = output_dir / "tile-0001.png"
            canvas.save(tile_path, format="PNG", optimize=True)
            tiles.append(
                {
                    "index": 0,
                    "path": str(tile_path.resolve()),
                    "sha256": _sha256_file(tile_path),
                    "width": canvas.width,
                    "height": canvas.height,
                    "synthetic_empty": True,
                }
            )
            canvas.close()
        manifest = {
            "schema": "threadsnap.screenshot-artifact.v2",
            "renderer_version": RENDERER_VERSION,
            "group": group,
            "version": version,
            "created_at": utc_now().isoformat(),
            "inputs": inputs,
            "tiles": [
                {key: value for key, value in item.items() if key != "path"} for item in tiles
            ],
            "items": artifact_items,
        }
        manifest_path = output_dir / "manifest.json"
        _atomic_write(
            manifest_path,
            json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
        )
        package_path = output_dir / "screenshot-artifact.zip"
        return {
            "tiles": tiles,
            "items": artifact_items,
            "package_path": str(package_path.resolve()),
            # PNG 和清单即为冻结成果；ZIP 只在首次下载所选版本时构建。
            "package_sha256": "",
        }

    def list_for_run(self, run_id: str, prefix: str) -> dict[str, Any]:
        with self.factory() as db:
            run = db.get(ExtractionRun, run_id)
            if not run:
                raise DomainError("RUN_NOT_FOUND", "指定提取批次不存在。", status_code=404)
            chain_ids = related_run_ids(db, run_id)
            root_id = chain_ids[0]
            groups = list(
                db.scalars(
                    select(ScreenshotArtifactGroup)
                    .where(ScreenshotArtifactGroup.chain_root_run_id == root_id)
                    .order_by(ScreenshotArtifactGroup.created_at)
                )
            )
            result = [self._group_dict(db, group, prefix) for group in groups]
            covered = {
                (group.platform_code, group.external_id, group.section, group.list_order)
                for group in groups
            }
            tasks = list(
                db.scalars(
                    select(CircleTask)
                    .where(CircleTask.run_id.in_(chain_ids))
                    .order_by(CircleTask.source_position)
                )
            )
            for task in tasks:
                key = (task.platform_code, task.external_id, task.section, task.list_order)
                if key in covered:
                    continue
                result.append(
                    {
                        "id": None,
                        "circle_name": task.circle_name,
                        "external_id": task.external_id,
                        "section": task.section,
                        "list_order": task.list_order,
                        "status": "not_applicable"
                        if run.input_mode == "url_list"
                        else "not_collected",
                        "current_version": 0,
                        "item_count": 0,
                        "negative_count": 0,
                        "evidence": [],
                        "artifact": None,
                    }
                )
                covered.add(key)
            return {"items": result}

    def _group_dict(
        self, db: Session, group: ScreenshotArtifactGroup, prefix: str
    ) -> dict[str, Any]:
        contributions = list(
            db.scalars(
                select(ScreenshotArtifactContribution).where(
                    ScreenshotArtifactContribution.group_id == group.id
                )
            )
        )
        task_ids = [item.circle_task_id for item in contributions]
        evidence = (
            list(
                db.scalars(
                    select(CirclePageEvidence)
                    .where(CirclePageEvidence.circle_task_id.in_(task_ids))
                    .order_by(CirclePageEvidence.captured_at, CirclePageEvidence.page_number)
                )
            )
            if task_ids
            else []
        )
        version = db.scalar(
            select(ScreenshotArtifactVersion).where(
                ScreenshotArtifactVersion.group_id == group.id,
                ScreenshotArtifactVersion.version == group.current_version,
            )
        )
        artifact = None
        if version:
            artifact = {
                "version": version.version,
                "created_at": version.created_at.isoformat(),
                "package_sha256": version.package_sha256,
                "download_url": (
                    f"{prefix}/screenshot-groups/{group.id}/download?version={version.version}"
                ),
                "tiles": [
                    {
                        **{key: value for key, value in tile.items() if key != "path"},
                        "image_url": (
                            f"{prefix}/screenshot-groups/{group.id}/tiles/{tile['index']}"
                            f"?version={version.version}&sha256={tile['sha256']}"
                        ),
                    }
                    for tile in version.tiles
                ],
                "items": version.items,
            }
        return {
            "id": group.id,
            "circle_name": group.circle_name,
            "external_id": group.external_id,
            "section": group.section,
            "list_order": group.list_order,
            "status": group.status,
            "current_version": group.current_version,
            "item_count": group.item_count,
            "negative_count": group.negative_count,
            "error_message": group.error_message,
            "evidence": [
                {
                    "id": item.id,
                    "page_number": item.page_number,
                    "exact_url": item.exact_url,
                    "captured_at": item.captured_at.isoformat(),
                    "sha256": item.screenshot_sha256,
                    "adapter_version": item.adapter_version,
                    "browser_version": item.browser_version,
                    "device_scale_factor": item.device_scale_factor,
                    "width": item.document_width,
                    "height": item.document_height,
                    "image_url": f"{prefix}/page-evidence/{item.id}/image",
                    "download_url": f"{prefix}/page-evidence/{item.id}/download",
                }
                for item in evidence
            ],
            "artifact": artifact,
        }

    def evidence_path(self, evidence_id: str) -> Path:
        with self.factory() as db:
            evidence = db.get(CirclePageEvidence, evidence_id)
            if not evidence:
                raise DomainError("EVIDENCE_NOT_FOUND", "指定原始页面证据不存在。", status_code=404)
            return Path(evidence.screenshot_path)

    def artifact_file(
        self,
        group_id: str,
        tile_index: int | None = None,
        *,
        version: int | None = None,
        sha256: str | None = None,
    ) -> Path:
        """取得明确版本的成果；首次下载才从冻结输入原子创建 ZIP。

        调用方的生命周期读租约须持续到响应发送结束，本锁只互斥渲染与打包。
        """

        with self._rebuild_lock, self.factory() as db:
            group = db.get(ScreenshotArtifactGroup, group_id)
            if not group or not (version or group.current_version):
                raise DomainError("ARTIFACT_NOT_FOUND", "指定截图成果尚未生成。", status_code=404)
            selected = db.scalar(
                select(ScreenshotArtifactVersion).where(
                    ScreenshotArtifactVersion.group_id == group.id,
                    ScreenshotArtifactVersion.version == (
                        version if version is not None else group.current_version
                    ),
                )
            )
            if not selected:
                raise DomainError("ARTIFACT_NOT_FOUND", "指定截图成果尚未生成。", status_code=404)
            version_root = self.settings.screenshot_artifact_dir / group.id / f"v{selected.version:04d}"
            if tile_index is None:
                path = self._package_file(selected, version_root)
                if sha256 and sha256 != selected.package_sha256:
                    raise DomainError(
                        "ARTIFACT_HASH_MISMATCH", "截图成果包版本校验值不匹配。", status_code=409
                    )
                return path
            tile = next((item for item in selected.tiles if int(item["index"]) == tile_index), None)
            if not tile:
                raise DomainError(
                    "ARTIFACT_TILE_NOT_FOUND", "指定截图分片不存在。", status_code=404
                )
            if sha256 and sha256 != tile["sha256"]:
                raise DomainError(
                    "ARTIFACT_HASH_MISMATCH", "截图成果分片版本校验值不匹配。", status_code=409
                )
            return self._artifact_path(tile["path"], version_root)

    def _artifact_path(self, raw_path: str | Path, root: Path) -> Path:
        """仅允许读取当前成果版本目录内的文件，不信任持久路径可任意寻址。"""

        path = Path(raw_path).resolve()
        resolved_root = root.resolve()
        if (
            not resolved_root.is_relative_to(self.settings.screenshot_artifact_dir.resolve())
            or not path.is_relative_to(resolved_root)
        ):
            raise DomainError(
                "ARTIFACT_PATH_INVALID", "截图成果文件路径超出允许范围。", status_code=409
            )
        return path

    def _package_file(self, version: ScreenshotArtifactVersion, root: Path) -> Path:
        """在重建锁内原样打包冻结清单和 PNG；失败只清理本次临时文件。"""

        package_path = self._artifact_path(version.package_path, root)
        if package_path.is_file():
            # 已发布的旧包不重压缩、不重写，首次发布后的崩溃只补登记校验值。
            if not version.package_sha256:
                self._record_package_hash(version, _sha256_file(package_path))
            return package_path
        manifest_path = self._artifact_path(root / "manifest.json", root)
        temporary = package_path.with_name(f".{package_path.name}.{uuid7()}.tmp")
        try:
            manifest_bytes = manifest_path.read_bytes()
            manifest = json.loads(manifest_bytes)
            if (
                manifest.get("group", {}).get("id") != version.group_id
                or manifest.get("version") != version.version
                or manifest.get("tiles") != [
                    {key: value for key, value in item.items() if key != "path"}
                    for item in version.tiles
                ]
                or manifest.get("items") != version.items
            ):
                raise ValueError("冻结清单与所选成果版本不一致。")
            members: set[str] = {"manifest.json"}
            with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_STORED) as archive:
                archive.writestr(_zip_member("manifest.json"), manifest_bytes)
                for tile in version.tiles:
                    path = self._artifact_path(tile["path"], root)
                    if path.suffix.lower() != ".png" or path.name in members:
                        raise ValueError("截图成果分片名称不合法或重复。")
                    members.add(path.name)
                    digest = hashlib.sha256()
                    # 对实际写入的同一字节流求哈希，避免校验后再次读取的时差。
                    with path.open("rb") as source, archive.open(
                        _zip_member(path.name), "w", force_zip64=True
                    ) as target:
                        for chunk in iter(lambda: source.read(1024 * 1024), b""):
                            digest.update(chunk)
                            target.write(chunk)
                    if digest.hexdigest() != tile["sha256"]:
                        raise ValueError("冻结截图成果分片校验失败。")
            package_hash = _sha256_file(temporary)
            if version.package_sha256 and package_hash != version.package_sha256:
                raise DomainError(
                    "ARTIFACT_PACKAGE_MISMATCH",
                    "缺失的历史截图包不能原样重建，请从备份恢复；未替换冻结成果。",
                    status_code=409,
                )
            os.replace(temporary, package_path)
            self._record_package_hash(version, package_hash)
            return package_path
        except DomainError:
            raise
        except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as exc:
            raise DomainError(
                "ARTIFACT_PACKAGE_FAILED",
                "截图成果包生成失败；冻结文件未改动，请检查存储与文件完整性。",
                status_code=409,
            ) from exc
        finally:
            temporary.unlink(missing_ok=True)

    def _record_package_hash(self, version: ScreenshotArtifactVersion, sha256: str) -> None:
        """ZIP 原子发布后单独登记哈希，不占用生成期间的数据库写事务。"""

        with self.factory.begin() as db:
            current = db.get(ScreenshotArtifactVersion, version.id)
            if not current:
                raise DomainError("ARTIFACT_NOT_FOUND", "截图成果已不存在。", status_code=404)
            current.package_sha256 = sha256
        version.package_sha256 = sha256

    def compact_identical_pngs(self) -> dict[str, int]:
        """维护窗口内合并登记 PNG 的相同物理内容，保留全部路径和逻辑归属。

        调用方必须取得排他生命周期门。只处理普通截图根目录内、登记哈希和实际
        字节都相同的文件；不支持硬链接时保持原文件，不重建图片或删除 ZIP。
        """

        result = {
            "registered_files": 0,
            "checked_files": 0,
            "linked_files": 0,
            "already_linked_files": 0,
            "skipped_files": 0,
            "failed_files": 0,
            "linked_logical_bytes": 0,
        }
        with self._rebuild_lock:
            registered: dict[str, set[str]] = {}
            with self.factory() as db:
                for path, digest in db.execute(
                    select(CirclePageEvidence.screenshot_path, CirclePageEvidence.screenshot_sha256)
                ):
                    registered.setdefault(path, set()).add(digest)
                for path, digest in db.execute(
                    select(ScreenshotArtifactTile.file_path, ScreenshotArtifactTile.file_sha256)
                ):
                    registered.setdefault(path, set()).add(digest)
                for tiles in db.scalars(select(ScreenshotArtifactVersion.tiles)):
                    for tile in tiles:
                        registered.setdefault(tile["path"], set()).add(tile["sha256"])
            result["registered_files"] = len(registered)
            candidates: dict[str, list[Path]] = {}
            roots = [
                self.settings.screenshot_evidence_dir.resolve(),
                self.settings.screenshot_artifact_dir.resolve(),
            ]
            for raw_path, hashes in registered.items():
                path = Path(raw_path)
                resolved = path.resolve()
                if (
                    len(hashes) != 1
                    or path.is_symlink()
                    or path.suffix.lower() != ".png"
                    or not any(resolved.is_relative_to(root) for root in roots)
                    or not path.is_file()
                ):
                    result["skipped_files"] += 1
                    continue
                digest = next(iter(hashes))
                candidates.setdefault(digest, []).append(resolved)
            for digest, paths in candidates.items():
                if len(paths) < 2:
                    continue
                sources: dict[int, Path] = {}
                for path in paths:
                    temporary = path.with_name(f".{path.name}.{uuid7()}.link")
                    try:
                        result["checked_files"] += 1
                        if _sha256_file(path) != digest:
                            result["skipped_files"] += 1
                            continue
                        stat = path.stat()
                        source = sources.get(stat.st_dev)
                        if source is None:
                            sources[stat.st_dev] = path
                            continue
                        if path.samefile(source):
                            result["already_linked_files"] += 1
                            continue
                        if not self._same_file_bytes(source, path):
                            result["skipped_files"] += 1
                            continue
                        os.link(source, temporary)
                        os.replace(temporary, path)
                        result["linked_files"] += 1
                        # 这是复用的逻辑字节数，不宣称 XFS/reflink 实际释放空间。
                        result["linked_logical_bytes"] += stat.st_size
                    except OSError:
                        result["failed_files"] += 1
                    finally:
                        temporary.unlink(missing_ok=True)
        return result

    @staticmethod
    def _same_file_bytes(left: Path, right: Path) -> bool:
        """哈希命中后仍逐块比较，存量物理合并只接受字节完全相同的输入。"""

        with left.open("rb") as first, right.open("rb") as second:
            while chunk := first.read(1024 * 1024):
                if chunk != second.read(len(chunk)):
                    return False
            return not second.read(1)

    def prepare_run_delete(self, run_id: str) -> tuple[list[str], list[str]]:
        """在外键级联前收集需要清理的原始文件和受影响成果组。"""

        with self.factory() as db:
            paths: list[str] = []
            for item in db.scalars(
                select(CirclePageEvidence).where(CirclePageEvidence.run_id == run_id)
            ):
                paths.extend([item.screenshot_path, item.manifest_path])
            group_ids = list(
                db.scalars(
                    select(ScreenshotArtifactContribution.group_id).where(
                        ScreenshotArtifactContribution.run_id == run_id
                    )
                )
            )
            return paths, group_ids

    def reconcile_after_run_delete(self, group_ids: list[str]) -> None:
        for group_id in set(group_ids):
            with self.factory.begin() as db:
                group = db.get(ScreenshotArtifactGroup, group_id)
                if not group:
                    continue
                remaining = db.scalar(
                    select(ScreenshotArtifactContribution.id)
                    .where(ScreenshotArtifactContribution.group_id == group_id)
                    .limit(1)
                )
                if not remaining:
                    db.delete(group)
                    shutil.rmtree(
                        self.settings.screenshot_artifact_dir / group_id, ignore_errors=True
                    )
                    continue
                surviving_run_id = db.scalar(
                    select(ScreenshotArtifactContribution.run_id)
                    .where(ScreenshotArtifactContribution.group_id == group_id)
                    .order_by(ScreenshotArtifactContribution.created_at)
                    .limit(1)
                )
                if surviving_run_id:
                    group.chain_root_run_id = self._root_run_id(db, surviving_run_id)
                group.dirty = True
                group.status = "waiting_for_sentiment"
            self.rebuild(group_id, reason="contribution_deleted")

    def mark_all_dirty_for_post(self, post_id: str) -> None:
        with self.factory.begin() as db:
            group_ids = list(
                db.scalars(
                    select(ScreenshotArtifactContribution.group_id)
                    .join(
                        CirclePageEvidenceItem,
                        CirclePageEvidenceItem.circle_task_id
                        == ScreenshotArtifactContribution.circle_task_id,
                    )
                    .where(CirclePageEvidenceItem.post_snapshot_id == post_id)
                )
            )
            for group_id in group_ids:
                group = db.get(ScreenshotArtifactGroup, group_id)
                if group:
                    group.dirty = True
                    group.status = "waiting_for_sentiment"
