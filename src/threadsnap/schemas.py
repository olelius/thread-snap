"""页面 API 与集成 API 共用的请求模型。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class ScheduleUpdate(BaseModel):
    times: list[str] = Field(default_factory=list)

    @field_validator("times")
    @classmethod
    def validate_times(cls, values: list[str]) -> list[str]:
        normalized: set[str] = set()
        for value in values:
            parts = value.split(":")
            if len(parts) != 2 or not all(part.isdigit() for part in parts):
                raise ValueError(f"时间 {value} 必须使用 HH:mm 格式")
            hour, minute = map(int, parts)
            if not 0 <= hour <= 23 or not 0 <= minute <= 59:
                raise ValueError(f"时间 {value} 超出有效范围")
            normalized.add(f"{hour:02d}:{minute:02d}")
        return sorted(normalized)


class PlatformConfigUpdate(BaseModel):
    enabled: bool
    auto_quantity: int = Field(ge=1)
    internal_concurrency: int = Field(ge=1)


class CircleRow(BaseModel):
    id: str | None = None
    platform_code: str
    url: str
    vehicle_id: str | None = None
    vehicle_name: str | None = None
    auto_enabled: bool = False
    section: str = "dynamic"


class CircleBatchUpdate(BaseModel):
    rows: list[CircleRow]


class ManualRunCreate(BaseModel):
    platform_code: str
    circle_ids: list[str] = Field(default_factory=list)
    circle_urls: list[str] = Field(default_factory=list)
    quantity: int = Field(ge=1)
    known_post_urls: list[str] = Field(default_factory=list)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=160)


class ExportCreate(BaseModel):
    template_version_id: str


class SessionImport(BaseModel):
    storage_state: dict[str, Any]


class PageResult(BaseModel):
    items: list[dict[str, Any]]
    total: int
    offset: int
    limit: int


RunStatus = Literal["queued", "running", "waiting_for_auth", "success", "partial_success", "failed"]
