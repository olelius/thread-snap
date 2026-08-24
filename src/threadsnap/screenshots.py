"""圈子页面原始证据、负面框选成果和版本生命周期。"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
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
RENDERER_VERSION = "v4-full-page-evidence-background"


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


def _pixel_distance(first: tuple[int, ...], second: tuple[int, ...]) -> int:
    return sum(abs(left - right) for left, right in zip(first[:3], second[:3], strict=True))


def _recover_card_crop_box(source: Image.Image, item: Any) -> tuple[int, int, int, int]:
    """从原始证据像素恢复卡片可见边界，旧证据异常时不改写原图或坐标。"""

    left = max(0, int(item.x))
    top = max(0, int(item.y))
    width = max(1, int(item.width))
    height = max(1, int(item.height))
    fallback = (
        left,
        top,
        min(source.width, left + width),
        min(source.height, top + height),
    )
    if left < 8 or top < 4 or left + 2 >= source.width:
        return fallback

    outside_x = left - 6
    inside_x = left + 2

    def edge_visible(y: int) -> bool:
        return _pixel_distance(
            source.getpixel((outside_x, y)),
            source.getpixel((inside_x, y)),
        ) >= 12

    search_top = range(max(4, top - 96), min(source.height - 4, top + 97))
    rising_edges = [
        y
        for y in search_top
        if edge_visible(y)
        and all(not edge_visible(y - offset) for offset in range(1, 5))
        and all(edge_visible(y + offset) for offset in range(3))
    ]
    if not rising_edges:
        return fallback
    recovered_top = min(rising_edges, key=lambda value: abs(value - top))

    expected_bottom = recovered_top + height
    search_bottom = range(
        max(recovered_top + max(20, height // 2), expected_bottom - 96),
        min(source.height - 4, expected_bottom + 97),
    )
    falling_edges = [
        y
        for y in search_bottom
        if not edge_visible(y)
        and all(edge_visible(y - offset) for offset in range(1, 4))
        and all(not edge_visible(y + offset) for offset in range(3))
    ]
    if not falling_edges:
        return fallback
    recovered_bottom = min(falling_edges, key=lambda value: abs(value - expected_bottom))

    probe_y = min(recovered_bottom - 1, recovered_top + 12)
    background = source.getpixel((outside_x, probe_y))
    horizontal = [
        (
            x,
            _pixel_distance(background, source.getpixel((x, probe_y))) >= 12,
        )
        for x in range(max(0, left - 32), min(source.width, left + width + 129))
    ]
    probe_index = next(
        (index for index, (x, _visible) in enumerate(horizontal) if x == inside_x),
        None,
    )
    if probe_index is None or not horizontal[probe_index][1]:
        return fallback
    start_index = probe_index
    end_index = probe_index
    while start_index > 0 and horizontal[start_index - 1][1]:
        start_index -= 1
    while end_index + 1 < len(horizontal) and horizontal[end_index + 1][1]:
        end_index += 1
    recovered_left = horizontal[start_index][0]
    recovered_right = horizontal[end_index][0] + 1
    recovered_width = recovered_right - recovered_left
    if not 0.8 * width <= recovered_width <= 1.3 * width:
        return fallback
    return recovered_left, recovered_top, recovered_right, recovered_bottom


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
            manifest = {
                "schema": "threadsnap.circle-page-evidence.v1",
                "captured_at": payload["captured_at"],
                "exact_url": payload["exact_url"],
                "page_number": page_number,
                "viewport": payload["viewport"],
                "document": payload["document"],
                "browser_version": payload["browser_version"],
                "adapter_version": payload["adapter_version"],
                "list_schema_version": "circle-page-v1",
                "rows": payload["rows"],
            }
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
                        list_schema_version="circle-page-v1",
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
            group_ids = list(db.scalars(
                select(ScreenshotArtifactGroup.id)
                .where(ScreenshotArtifactGroup.dirty.is_(True))
                .order_by(ScreenshotArtifactGroup.updated_at)
            ))
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
            if any(task.status not in TERMINAL_TASK_STATUSES for task in tasks):
                with nullcontext():
                    group.status = "evidence_running"
                return False
            rows = list(
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
            ) if contributions else []
            deduped: OrderedDict[str, tuple[Any, Any, Any]] = OrderedDict()
            for item, post, evidence in rows:
                deduped.setdefault(post.platform_post_id, (item, post, evidence))
            selected = list(deduped.values())
            if any(post.sentiment_result is None for _item, post, _evidence in selected):
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
                    run.number if (run := db.get(ExtractionRun, evidence.run_id)) else evidence.run_id
                )
                for _item, _post, evidence in selected
            }
            inputs = [
                {
                    "post_id": post.id,
                    "platform_post_id": post.platform_post_id,
                    "sentiment": post.sentiment_result,
                    "sentiment_updated_at": (
                        post.sentiment_updated_at.isoformat() if post.sentiment_updated_at else None
                    ),
                    "evidence_id": evidence.id,
                    "evidence_sha256": evidence.screenshot_sha256,
                    "evidence_run_id": evidence.run_id,
                    "evidence_page_number": evidence.page_number,
                    "run_number": run_numbers[evidence.run_id],
                    "captured_at": evidence.captured_at.isoformat(),
                    "rect": [item.x, item.y, item.width, item.height],
                }
                for item, post, evidence in selected
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
            version_number = (latest.version if latest else 0) + 1
            group_snapshot = {
                "id": group.id,
                "circle_name": group.circle_name,
                "external_id": group.external_id,
                "list_order": group.list_order,
            }
            group.status = "rendering"
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
                    negative_count=sum(
                        post.sentiment_result == "negative" for _item, post, _evidence in selected
                    ),
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
                for selected_index, item, post in page_cards:
                    left, top, right, bottom = _recover_card_crop_box(source, item)
                    if post.sentiment_result == "negative":
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
                            "sentiment_result": post.sentiment_result,
                            "run_number": inputs[selected_index]["run_number"],
                            "captured_at": inputs[selected_index]["captured_at"],
                            "tile_index": tile_index,
                            "y": top,
                            "height": bottom - top,
                            "source_rect": [left, top, right - left, bottom - top],
                        }
                    )
            tile_path = output_dir / f"tile-{tile_index + 1:04d}.png"
            canvas.save(tile_path, format="PNG", optimize=True)
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
            "tiles": [{key: value for key, value in item.items() if key != "path"} for item in tiles],
            "items": artifact_items,
        }
        manifest_path = output_dir / "manifest.json"
        _atomic_write(
            manifest_path,
            json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
        )
        package_path = output_dir / "screenshot-artifact.zip"
        with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(manifest_path, "manifest.json")
            for tile in tiles:
                archive.write(tile["path"], Path(tile["path"]).name)
        return {
            "tiles": tiles,
            "items": artifact_items,
            "package_path": str(package_path.resolve()),
            "package_sha256": _sha256_file(package_path),
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
                        "status": "not_applicable" if run.input_mode == "url_list" else "not_collected",
                        "current_version": 0,
                        "item_count": 0,
                        "negative_count": 0,
                        "evidence": [],
                        "artifact": None,
                    }
                )
                covered.add(key)
            return {"items": result}

    def _group_dict(self, db: Session, group: ScreenshotArtifactGroup, prefix: str) -> dict[str, Any]:
        contributions = list(
            db.scalars(
                select(ScreenshotArtifactContribution).where(
                    ScreenshotArtifactContribution.group_id == group.id
                )
            )
        )
        task_ids = [item.circle_task_id for item in contributions]
        evidence = list(
            db.scalars(
                select(CirclePageEvidence)
                .where(CirclePageEvidence.circle_task_id.in_(task_ids))
                .order_by(CirclePageEvidence.captured_at, CirclePageEvidence.page_number)
            )
        ) if task_ids else []
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
                "download_url": f"{prefix}/screenshot-groups/{group.id}/download",
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

    def artifact_file(self, group_id: str, tile_index: int | None = None) -> Path:
        with self.factory() as db:
            group = db.get(ScreenshotArtifactGroup, group_id)
            if not group or not group.current_version:
                raise DomainError("ARTIFACT_NOT_FOUND", "指定截图成果尚未生成。", status_code=404)
            version = db.scalar(
                select(ScreenshotArtifactVersion).where(
                    ScreenshotArtifactVersion.group_id == group.id,
                    ScreenshotArtifactVersion.version == group.current_version,
                )
            )
            if not version:
                raise DomainError("ARTIFACT_NOT_FOUND", "指定截图成果尚未生成。", status_code=404)
            if tile_index is None:
                return Path(version.package_path)
            tile = next((item for item in version.tiles if int(item["index"]) == tile_index), None)
            if not tile:
                raise DomainError("ARTIFACT_TILE_NOT_FOUND", "指定截图分片不存在。", status_code=404)
            return Path(tile["path"])

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
                    shutil.rmtree(self.settings.screenshot_artifact_dir / group_id, ignore_errors=True)
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
