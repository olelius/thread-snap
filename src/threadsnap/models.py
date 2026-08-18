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
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    comments: Mapped[list["CommentSnapshot"]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True
    )


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
