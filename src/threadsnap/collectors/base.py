"""平台采集器共享类型、稳定错误与最小运行协议。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Protocol, TypedDict


class AuthenticationRequired(RuntimeError):
    """平台明确要求认证，并携带原批次已经形成的进度。"""

    def __init__(
        self,
        message: str,
        *,
        trigger_url: str | None = None,
        records: list[dict[str, Any]] | None = None,
        failures: list[dict[str, Any]] | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.trigger_url = trigger_url
        self.records = records or []
        self.failures = failures or []


class CollectorFailure(RuntimeError):
    """带稳定英文错误码和中文说明的采集失败。"""

    def __init__(self, code: str, message: str, *, trigger_url: str | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.trigger_url = trigger_url


@dataclass(frozen=True)
class CircleSource:
    """用户来源 URL 解析后的稳定平台身份与列表顺序。"""

    external_id: str
    url: str
    list_order: str
    raw_status: dict[str, Any] = field(default_factory=dict)


class CommentRecord(TypedDict):
    """持久化前的一级评论快照。"""

    platform_comment_id: str | None
    author: str | None
    content: str | None
    published_at: datetime | None
    like_count: int | None


class PostRecord(TypedDict, total=False):
    """所有平台交给 Worker 的平台中立帖子记录。"""

    platform_post_id: str
    url: str
    title: str | None
    author: str | None
    published_at: datetime | None
    content: str | None
    image_urls: list[str]
    video_urls: list[str]
    reply_count: int | None
    like_count: int | None
    section: str | None
    visibility: str
    raw_status: dict[str, Any] | None
    comments: list[CommentRecord]
    order_index: int


class FailureRecord(TypedDict):
    """单个候选或输入 URL 的稳定失败记录。"""

    url: str
    code: str
    message: str
    source_index: int


class CollectionResult(TypedDict):
    """圈子发现与 URL 清单共用的批次内返回结构。"""

    records: list[dict[str, Any]]
    failures: list[dict[str, Any]]
    stop_reason: str


class ValidatedCircle(TypedDict, total=False):
    """来源验证成功后写回配置与任务快照的结果。"""

    platform_code: str
    external_id: str
    name: str
    url: str
    section: str
    sort: str
    sample_post_id: str
    adapter_version: str
    raw_status: dict[str, Any]


ProgressCallback = Callable[[dict[str, Any] | None, dict[str, Any] | None], None]
PageEvidenceCallback = Callable[[dict[str, Any]], None]


class Collector(Protocol):
    """Worker 依赖的最小采集器协议；平台私有字段只能留在适配器内部。"""

    code: str
    display_name: str
    adapter_version: str
    concurrency: int
    supports_page_evidence: bool
    supports_live_video_resolution: bool

    def validate_circle(self, circle_url: str) -> dict[str, Any]: ...

    def collect_circle(
        self,
        circle_url: str,
        target_count: int,
        skip_post_ids: set[str] | None = None,
        on_progress: ProgressCallback | None = None,
        on_page_evidence: PageEvidenceCallback | None = None,
    ) -> dict[str, Any]: ...

    def collect_urls(
        self,
        urls: list[str],
        on_progress: ProgressCallback | None = None,
    ) -> dict[str, Any]: ...
