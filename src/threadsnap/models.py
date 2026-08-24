"""第一版领域持久化模型。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base, UTCDateTime
from .ids import source_key, uuid7


def utc_now() -> datetime:
    """返回带 UTC 时区的当前时间。"""

    return datetime.now(timezone.utc)


class PlatformConfig(Base):
    __tablename__ = "platform_configs"

    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(64), nullable=False)
    adapter_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="not_integrated"
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    internal_concurrency: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    min_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    max_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=2000)
    min_concurrency: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    max_concurrency: Mapped[int] = mapped_column(Integer, nullable=False, default=8)
    adapter_version: Mapped[str | None] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, onupdate=utc_now)


class ScheduleConfig(Base):
    __tablename__ = "schedule_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    timezone_name: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Shanghai")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, onupdate=utc_now)


class ExtractionRule(Base):
    __tablename__ = "extraction_rules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, onupdate=utc_now)
    versions: Mapped[list["ExtractionRuleVersion"]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True
    )


class ExtractionRuleVersion(Base):
    __tablename__ = "extraction_rule_versions"
    __table_args__ = (UniqueConstraint("rule_id", "version", name="uq_extraction_rule_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    rule_id: Mapped[str] = mapped_column(
        ForeignKey("extraction_rules.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    platform_quantities: Mapped[dict[str, int]] = mapped_column(JSON, nullable=False, default=dict)
    selected_circle_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class ScheduleNode(Base):
    __tablename__ = "schedule_nodes"
    __table_args__ = (Index("ix_schedule_nodes_enabled_time", "enabled", "time_of_day"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    weekdays: Mapped[list[int]] = mapped_column(JSON, nullable=False, default=list)
    time_of_day: Mapped[str] = mapped_column(String(8), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    legacy_rule_id: Mapped[str] = mapped_column(
        "rule_id",
        ForeignKey("extraction_rules.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, onupdate=utc_now)


class ScheduleNodeRule(Base):
    __tablename__ = "schedule_node_rules"
    __table_args__ = (
        UniqueConstraint("schedule_node_id", "position", name="uq_schedule_node_rule_position"),
    )

    schedule_node_id: Mapped[str] = mapped_column(
        ForeignKey("schedule_nodes.id", ondelete="CASCADE"), primary_key=True
    )
    rule_id: Mapped[str] = mapped_column(
        ForeignKey("extraction_rules.id", ondelete="RESTRICT"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)


class Vehicle(Base):
    __tablename__ = "vehicles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, onupdate=utc_now)
    circles: Mapped[list["Circle"]] = relationship(back_populates="vehicle", passive_deletes=True)


class Circle(Base):
    __tablename__ = "circles"
    __table_args__ = (
        UniqueConstraint(
            "platform_code",
            "external_id",
            "section",
            "list_order",
            name="uq_circle_platform_source",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    export_key: Mapped[str] = mapped_column(
        String(10), nullable=False, unique=True, default=source_key
    )
    platform_code: Mapped[str] = mapped_column(ForeignKey("platform_configs.code"), nullable=False)
    external_id: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str | None] = mapped_column(String(200))
    url: Mapped[str] = mapped_column(Text, nullable=False)
    section: Mapped[str] = mapped_column(String(32), nullable=False, default="dynamic")
    list_order: Mapped[str] = mapped_column(
        String(32), nullable=False, default="latest_reply"
    )
    vehicle_id: Mapped[str | None] = mapped_column(ForeignKey("vehicles.id", ondelete="SET NULL"))
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False, default="configured")
    auto_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    validation_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unverified")
    validation_error: Mapped[str | None] = mapped_column(Text)
    first_validated_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    validated_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    adapter_version: Mapped[str | None] = mapped_column(String(64))
    last_used_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, onupdate=utc_now)
    vehicle: Mapped[Vehicle | None] = relationship(back_populates="circles")


class ValidationJob(Base):
    __tablename__ = "validation_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    circle_id: Mapped[str] = mapped_column(
        ForeignKey("circles.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class ExtractionRun(Base):
    __tablename__ = "extraction_runs"
    __table_args__ = (
        UniqueConstraint("idempotency_scope", "idempotency_key", name="uq_run_idempotency"),
        Index("ix_runs_status_created", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    number: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(32), nullable=False)
    input_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="circle_discovery")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    idempotency_scope: Mapped[str] = mapped_column(String(32), nullable=False, default="api")
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    related_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("extraction_runs.id", ondelete="SET NULL")
    )
    schedule_node_id: Mapped[str | None] = mapped_column(
        ForeignKey("schedule_nodes.id", ondelete="SET NULL")
    )
    extraction_rule_id: Mapped[str | None] = mapped_column(
        ForeignKey("extraction_rules.id", ondelete="SET NULL")
    )
    extraction_rule_version: Mapped[int | None] = mapped_column(Integer)
    config_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    planned_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    waiting_reason: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    summary_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    queued_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    tasks: Mapped[list["CircleTask"]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True
    )


class ExtractionRunRule(Base):
    __tablename__ = "extraction_run_rules"
    __table_args__ = (
        UniqueConstraint("run_id", "position", name="uq_extraction_run_rule_position"),
    )

    run_id: Mapped[str] = mapped_column(
        ForeignKey("extraction_runs.id", ondelete="CASCADE"), primary_key=True
    )
    rule_id: Mapped[str] = mapped_column(
        ForeignKey("extraction_rules.id", ondelete="RESTRICT"), primary_key=True
    )
    rule_version: Mapped[int] = mapped_column(Integer, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)


class CircleTask(Base):
    __tablename__ = "circle_tasks"
    __table_args__ = (
        Index(
            "ix_circle_tasks_platform_queue",
            "platform_code",
            "status",
            "queue_sequence",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("extraction_runs.id", ondelete="CASCADE"), nullable=False
    )
    circle_id: Mapped[str | None] = mapped_column(ForeignKey("circles.id", ondelete="SET NULL"))
    platform_code: Mapped[str] = mapped_column(String(32), nullable=False)
    external_id: Mapped[str] = mapped_column(String(80), nullable=False)
    circle_name: Mapped[str | None] = mapped_column(String(200))
    circle_url: Mapped[str] = mapped_column(Text, nullable=False)
    section: Mapped[str] = mapped_column(String(32), nullable=False, default="dynamic")
    list_order: Mapped[str] = mapped_column(
        String(32), nullable=False, default="latest_reply"
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    queue_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    source_position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    target_count: Mapped[int] = mapped_column(Integer, nullable=False)
    completed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    config_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    checkpoint: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    stop_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class PostSnapshot(Base):
    __tablename__ = "post_snapshots"
    __table_args__ = (UniqueConstraint("circle_task_id", "platform_post_id", name="uq_task_post"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("extraction_runs.id", ondelete="CASCADE"), nullable=False
    )
    circle_task_id: Mapped[str] = mapped_column(
        ForeignKey("circle_tasks.id", ondelete="CASCADE"), nullable=False
    )
    platform_post_id: Mapped[str] = mapped_column(String(80), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    author: Mapped[str | None] = mapped_column(String(240))
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    content: Mapped[str | None] = mapped_column(Text)
    image_urls: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    video_urls: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    reply_count: Mapped[int | None] = mapped_column(Integer)
    like_count: Mapped[int | None] = mapped_column(Integer)
    section: Mapped[str | None] = mapped_column(String(64))
    visibility: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    raw_status: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    analysis_status: Mapped[str | None] = mapped_column(String(32))
    sentiment_result: Mapped[str | None] = mapped_column(String(32))
    sentiment_source: Mapped[str | None] = mapped_column(String(32))
    sentiment_updated_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    comments: Mapped[list["CommentSnapshot"]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True
    )


class CirclePageEvidence(Base):
    """圈子列表页的不可变原始页面证据。"""

    __tablename__ = "circle_page_evidence"
    __table_args__ = (
        UniqueConstraint("circle_task_id", "page_number", name="uq_circle_page_evidence_task_page"),
        Index("ix_circle_page_evidence_run", "run_id", "circle_task_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("extraction_runs.id", ondelete="CASCADE"), nullable=False
    )
    circle_task_id: Mapped[str] = mapped_column(
        ForeignKey("circle_tasks.id", ondelete="CASCADE"), nullable=False
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    exact_url: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ready")
    adapter_version: Mapped[str] = mapped_column(String(64), nullable=False)
    browser_version: Mapped[str] = mapped_column(String(80), nullable=False)
    list_schema_version: Mapped[str] = mapped_column(
        String(32), nullable=False, default="circle-page-v1"
    )
    device_scale_factor: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    viewport_width: Mapped[int] = mapped_column(Integer, nullable=False)
    viewport_height: Mapped[int] = mapped_column(Integer, nullable=False)
    document_width: Mapped[int] = mapped_column(Integer, nullable=False)
    document_height: Mapped[int] = mapped_column(Integer, nullable=False)
    screenshot_path: Mapped[str] = mapped_column(Text, nullable=False)
    screenshot_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest_path: Mapped[str] = mapped_column(Text, nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    error_message: Mapped[str | None] = mapped_column(Text)


class CirclePageEvidenceItem(Base):
    """同一冻结 DOM 中帖子卡片的位置和身份清单。"""

    __tablename__ = "circle_page_evidence_items"
    __table_args__ = (
        UniqueConstraint("evidence_id", "platform_post_id", name="uq_evidence_post"),
        Index("ix_evidence_item_task_post", "circle_task_id", "platform_post_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    evidence_id: Mapped[str] = mapped_column(
        ForeignKey("circle_page_evidence.id", ondelete="CASCADE"), nullable=False
    )
    circle_task_id: Mapped[str] = mapped_column(
        ForeignKey("circle_tasks.id", ondelete="CASCADE"), nullable=False
    )
    post_snapshot_id: Mapped[str | None] = mapped_column(
        ForeignKey("post_snapshots.id", ondelete="SET NULL")
    )
    platform_post_id: Mapped[str] = mapped_column(String(80), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    source_position: Mapped[int] = mapped_column(Integer, nullable=False)
    x: Mapped[int] = mapped_column(Integer, nullable=False)
    y: Mapped[int] = mapped_column(Integer, nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    text_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    image_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class ScreenshotArtifactGroup(Base):
    """同一原始批次链、同一圈子来源的稳定成果组。"""

    __tablename__ = "screenshot_artifact_groups"
    __table_args__ = (
        UniqueConstraint(
            "chain_root_run_id",
            "platform_code",
            "external_id",
            "section",
            "list_order",
            name="uq_screenshot_artifact_source",
        ),
        Index("ix_screenshot_artifact_group_status", "status", "updated_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    chain_root_run_id: Mapped[str] = mapped_column(String(36), nullable=False)
    platform_code: Mapped[str] = mapped_column(String(32), nullable=False)
    external_id: Mapped[str] = mapped_column(String(80), nullable=False)
    circle_name: Mapped[str | None] = mapped_column(String(200))
    section: Mapped[str] = mapped_column(String(32), nullable=False)
    list_order: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="evidence_pending")
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    negative_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    dirty: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, onupdate=utc_now)


class ScreenshotArtifactContribution(Base):
    """成果组与原始/补提任务之间的贡献关系。"""

    __tablename__ = "screenshot_artifact_contributions"
    __table_args__ = (UniqueConstraint("group_id", "circle_task_id", name="uq_group_task"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    group_id: Mapped[str] = mapped_column(
        ForeignKey("screenshot_artifact_groups.id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[str] = mapped_column(
        ForeignKey("extraction_runs.id", ondelete="CASCADE"), nullable=False
    )
    circle_task_id: Mapped[str] = mapped_column(
        ForeignKey("circle_tasks.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class ScreenshotArtifactVersion(Base):
    """基于当前有效帖子与舆情结论生成的不可变成果版本。"""

    __tablename__ = "screenshot_artifact_versions"
    __table_args__ = (
        UniqueConstraint("group_id", "version", name="uq_screenshot_artifact_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    group_id: Mapped[str] = mapped_column(
        ForeignKey("screenshot_artifact_groups.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ready")
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
    input_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    item_count: Mapped[int] = mapped_column(Integer, nullable=False)
    negative_count: Mapped[int] = mapped_column(Integer, nullable=False)
    tiles: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    items: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    package_path: Mapped[str] = mapped_column(Text, nullable=False)
    package_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    error_message: Mapped[str | None] = mapped_column(Text)


class ScreenshotArtifactTile(Base):
    """成果版本的有序无损 PNG 分片。"""

    __tablename__ = "screenshot_artifact_tiles"
    __table_args__ = (UniqueConstraint("version_id", "tile_index", name="uq_version_tile"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    version_id: Mapped[str] = mapped_column(
        ForeignKey("screenshot_artifact_versions.id", ondelete="CASCADE"), nullable=False
    )
    tile_index: Mapped[int] = mapped_column(Integer, nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)


class ScreenshotArtifactItem(Base):
    """成果版本内每个卡片的审计位置、来源和有效结论。"""

    __tablename__ = "screenshot_artifact_items"
    __table_args__ = (
        UniqueConstraint("version_id", "platform_post_id", name="uq_version_artifact_post"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    version_id: Mapped[str] = mapped_column(
        ForeignKey("screenshot_artifact_versions.id", ondelete="CASCADE"), nullable=False
    )
    post_snapshot_id: Mapped[str | None] = mapped_column(
        ForeignKey("post_snapshots.id", ondelete="SET NULL")
    )
    platform_post_id: Mapped[str] = mapped_column(String(80), nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    sentiment_result: Mapped[str] = mapped_column(String(32), nullable=False)
    contribution_run_number: Mapped[str] = mapped_column(String(32), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    tile_index: Mapped[int] = mapped_column(Integer, nullable=False)
    y: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)


class SentimentConfig(Base):
    """舆情模型的单例运行配置；密钥只保存密文。"""

    __tablename__ = "sentiment_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    base_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    encrypted_api_key: Mapped[bytes | None] = mapped_column(LargeBinary)
    deepseek_base_url: Mapped[str] = mapped_column(
        Text, nullable=False, default="https://api.deepseek.com"
    )
    deepseek_encrypted_api_key: Mapped[bytes | None] = mapped_column(LargeBinary)
    model_code: Mapped[str] = mapped_column(
        String(120), nullable=False, default="qwen3.5-omni-plus-2026-03-15"
    )
    cloud_concurrency: Mapped[int] = mapped_column(Integer, nullable=False, default=8)
    validation_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="unverified"
    )
    validation_error: Mapped[str | None] = mapped_column(Text)
    validated_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    subject_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    brand: Mapped[str] = mapped_column(String(120), nullable=False, default="奇瑞")
    products: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    supplement: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, onupdate=utc_now)


class SentimentAnalysis(Base):
    """每个帖子快照的一条持久舆情分析任务与审计结果。"""

    __tablename__ = "sentiment_analyses"
    __table_args__ = (
        UniqueConstraint("post_id", name="uq_sentiment_analysis_post"),
        Index("ix_sentiment_analysis_queue", "status", "created_at"),
        Index("ix_sentiment_analysis_identity", "platform_code", "platform_post_id", "input_hash"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    post_id: Mapped[str] = mapped_column(
        ForeignKey("post_snapshots.id", ondelete="CASCADE"), nullable=False
    )
    platform_code: Mapped[str] = mapped_column(String(32), nullable=False)
    platform_post_id: Mapped[str] = mapped_column(String(80), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    config_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    subject_version: Mapped[int] = mapped_column(Integer, nullable=False)
    subject_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    model_code: Mapped[str] = mapped_column(String(120), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False, default="v1")
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    result: Mapped[str | None] = mapped_column(String(32))
    matched_subjects: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    primary_category: Mapped[str | None] = mapped_column(String(64))
    secondary_categories: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    summary: Mapped[str | None] = mapped_column(Text)
    modalities: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    raw_response: Mapped[str | None] = mapped_column(Text)
    attempt_failures: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    locally_recovered: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    provider_request_id: Mapped[str | None] = mapped_column(String(200))
    usage: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(Text)
    reused_from_analysis_id: Mapped[str | None] = mapped_column(
        ForeignKey("sentiment_analyses.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class ManualSentimentRevision(Base):
    """人工修订追加历史；恢复 AI 也以事件记录而非删除历史。"""

    __tablename__ = "manual_sentiment_revisions"
    __table_args__ = (Index("ix_manual_sentiment_post_created", "post_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    post_id: Mapped[str] = mapped_column(
        ForeignKey("post_snapshots.id", ondelete="CASCADE"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    result: Mapped[str | None] = mapped_column(String(32))
    primary_category: Mapped[str | None] = mapped_column(String(64))
    secondary_categories: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    note: Mapped[str | None] = mapped_column(Text)
    inherited_from_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("manual_sentiment_revisions.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class CommentSnapshot(Base):
    __tablename__ = "comment_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    post_id: Mapped[str] = mapped_column(
        ForeignKey("post_snapshots.id", ondelete="CASCADE"), nullable=False
    )
    platform_comment_id: Mapped[str | None] = mapped_column(String(80))
    author: Mapped[str | None] = mapped_column(String(240))
    content: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    like_count: Mapped[int | None] = mapped_column(Integer)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)


class Template(Base):
    __tablename__ = "templates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    name: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)
    hidden: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    versions: Mapped[list["TemplateVersion"]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True
    )


class TemplateVersion(Base):
    __tablename__ = "template_versions"
    __table_args__ = (UniqueConstraint("template_id", "version", name="uq_template_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    template_id: Mapped[str] = mapped_column(
        ForeignKey("templates.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    bindings: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class ExportRecord(Base):
    __tablename__ = "export_records"
    __table_args__ = (
        UniqueConstraint(
            "run_id", "summary_version", "template_version_id", name="uq_export_version"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("extraction_runs.id", ondelete="CASCADE"), nullable=False
    )
    summary_version: Mapped[int] = mapped_column(Integer, nullable=False)
    template_version_id: Mapped[str] = mapped_column(
        ForeignKey("template_versions.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    file_path: Mapped[str | None] = mapped_column(Text)
    file_sha256: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class PlatformSession(Base):
    __tablename__ = "platform_sessions"

    platform_code: Mapped[str] = mapped_column(String(32), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="missing")
    encrypted_state: Mapped[bytes | None] = mapped_column(LargeBinary)
    last_verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    error_message: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, onupdate=utc_now)


class ScheduleEvent(Base):
    __tablename__ = "schedule_events"
    __table_args__ = (
        UniqueConstraint("schedule_node_id", "planned_at", name="uq_schedule_node_planned"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    planned_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    schedule_node_id: Mapped[str | None] = mapped_column(
        ForeignKey("schedule_nodes.id", ondelete="SET NULL")
    )
    schedule_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    extraction_rule_id: Mapped[str | None] = mapped_column(
        ForeignKey("extraction_rules.id", ondelete="SET NULL")
    )
    extraction_rule_version: Mapped[int | None] = mapped_column(Integer)
    rule_snapshots: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    run_id: Mapped[str | None] = mapped_column(
        ForeignKey("extraction_runs.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class ReputationScopeDraft(Base):
    """口碑巡检唯一服务端草稿。"""

    __tablename__ = "reputation_scope_drafts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default="current")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    published_version_id: Mapped[str | None] = mapped_column(String(36))
    source_sha256: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, onupdate=utc_now)


class ReputationScopeVersion(Base):
    """已经发布且不可变的口碑巡检范围版本。"""

    __tablename__ = "reputation_scope_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    version: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    source_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    published_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class ReputationRun(Base):
    """与帖子提取批次隔离的口碑巡检运行。"""

    __tablename__ = "reputation_runs"
    __table_args__ = (
        Index("ix_reputation_runs_created", "source_type", "created_at"),
        Index("ix_reputation_runs_status", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    number: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    source_type: Mapped[str] = mapped_column(String(24), nullable=False)
    scenario_id: Mapped[str | None] = mapped_column(String(48))
    fixture_version: Mapped[str | None] = mapped_column(String(32))
    input_hash: Mapped[str | None] = mapped_column(String(64))
    run_type: Mapped[str] = mapped_column(String(32), nullable=False)
    planned_date: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    platform_codes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    planned_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    required_evidence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    complete_evidence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    report_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    report_text: Mapped[str | None] = mapped_column(Text)
    report_path: Mapped[str | None] = mapped_column(Text)
    xlsx_path: Mapped[str | None] = mapped_column(Text)
    evidence_zip_path: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class ReputationResult(Base):
    """一次运行中一个车型平台组合的完整结果。"""

    __tablename__ = "reputation_results"
    __table_args__ = (
        UniqueConstraint("run_id", "vehicle_id", "platform_code", name="uq_reputation_result"),
        Index("ix_reputation_results_run_order", "run_id", "role_position", "vehicle_position"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("reputation_runs.id", ondelete="CASCADE"), nullable=False
    )
    vehicle_id: Mapped[str] = mapped_column(String(64), nullable=False)
    series_name: Mapped[str] = mapped_column(String(120), nullable=False)
    vehicle_name: Mapped[str] = mapped_column(String(160), nullable=False)
    role: Mapped[str] = mapped_column(String(24), nullable=False)
    role_position: Mapped[int] = mapped_column(Integer, nullable=False)
    vehicle_position: Mapped[int] = mapped_column(Integer, nullable=False)
    platform_code: Mapped[str] = mapped_column(String(32), nullable=False)
    platform_name: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    evidence_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    collected_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class ReputationEvidence(Base):
    """一个车型平台组合的完整原页和同源指标区域证据。"""

    __tablename__ = "reputation_evidence"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    result_id: Mapped[str] = mapped_column(
        ForeignKey("reputation_results.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    full_page_path: Mapped[str] = mapped_column(Text, nullable=False)
    metric_region_path: Mapped[str] = mapped_column(Text, nullable=False)
    full_page_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    metric_region_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
