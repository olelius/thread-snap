"""页面 API 与集成 API 共用的请求模型。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExtractionRuleDraft(StrictModel):
    id: str = Field(min_length=8, max_length=36)
    name: str = Field(min_length=1, max_length=120)
    platform_quantities: dict[str, int] = Field(default_factory=dict)
    circle_ids: list[str] = Field(default_factory=list)


class ScheduleNodeDraft(StrictModel):
    id: str = Field(min_length=8, max_length=36)
    weekdays: list[int] = Field(min_length=1)
    time: str
    enabled: bool = True
    rule_id: str = Field(min_length=8, max_length=36)

    @field_validator("weekdays")
    @classmethod
    def validate_weekdays(cls, values: list[int]) -> list[int]:
        if any(value < 0 or value > 6 for value in values):
            raise ValueError("星期必须使用 0 到 6，其中 0 表示星期一")
        return sorted(set(values))

    @field_validator("time")
    @classmethod
    def validate_time(cls, value: str) -> str:
        parts = value.split(":")
        if len(parts) != 3 or not all(part.isdigit() for part in parts):
            raise ValueError(f"时间 {value} 必须使用 HH:mm:ss 格式")
        hour, minute, second = map(int, parts)
        if not 0 <= hour <= 23 or not 0 <= minute <= 59 or not 0 <= second <= 59:
            raise ValueError(f"时间 {value} 超出有效范围")
        return f"{hour:02d}:{minute:02d}:{second:02d}"


class ExtractionPlanUpdate(StrictModel):
    revision: int = Field(ge=1)
    rules: list[ExtractionRuleDraft] = Field(default_factory=list)
    nodes: list[ScheduleNodeDraft] = Field(default_factory=list)


class PlatformConfigUpdate(StrictModel):
    enabled: bool
    internal_concurrency: int = Field(ge=1)


class CircleRow(StrictModel):
    id: str | None = None
    platform_code: str
    url: str
    vehicle_id: str | None = None
    vehicle_name: str | None = None
    auto_enabled: bool = False
    section: str = "dynamic"


class CircleBatchUpdate(StrictModel):
    rows: list[CircleRow]
    deleted_ids: list[str] = Field(default_factory=list)


class ManualRunCreate(StrictModel):
    platform_code: str
    circle_ids: list[str] = Field(default_factory=list)
    circle_urls: list[str] = Field(default_factory=list)
    quantity: int = Field(ge=1)
    known_post_urls: list[str] = Field(default_factory=list)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=160)


class ExportCreate(StrictModel):
    template_version_id: str


class SessionImport(StrictModel):
    storage_state: dict[str, Any]


class PageResult(BaseModel):
    items: list[dict[str, Any]]
    total: int
    offset: int
    limit: int


RunStatus = Literal["queued", "running", "waiting_for_auth", "success", "partial_success", "failed"]
