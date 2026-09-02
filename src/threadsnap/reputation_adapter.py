"""垂媒口碑巡检适配器的公共合同。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


class ReputationAdapterError(RuntimeError):
    """携带稳定阶段错误码的真实页面验证失败。"""

    def __init__(self, code: str, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


@dataclass(frozen=True)
class ReputationMappingTarget:
    """一次真实页面验证所需的冻结车型映射。"""

    vehicle_id: str
    platform_vehicle_id: str
    platform_url: str
    platform_display_name: str
    mapping_hash: str


@dataclass(frozen=True)
class ReputationPageResult:
    """一次页面访问通过身份、指标和证据门禁后的真实结果。"""

    vehicle_id: str
    platform_vehicle_id: str
    mapping_hash: str
    final_url: str
    actual_name: str
    score_raw: str | None
    rank_raw: str | None
    volume_raw: str | None
    review_article_count_raw: str | None
    review_article_count_url: str | None
    rank_scope: str
    measurements: list[dict[str, Any]]
    full_page_path: Path | None
    metric_region_path: Path | None
    full_page_sha256: str | None
    metric_region_sha256: str | None
    width: int
    height: int
    metric_rect: dict[str, float]
    duration_ms: int
    negative_rate_raw: str | None = None
    negative_rate_url: str | None = None
    negative_rate_positive_count: int | None = None
    negative_rate_negative_count: int | None = None
    reputation_not_available: bool = False


class ReputationAdapter(Protocol):
    """所有垂媒真实页面适配器必须满足的最小运行接口。"""

    code: str
    display_name: str
    adapter_version: str
    validation_contract_version: str

    def validate_sync(
        self,
        targets: list[ReputationMappingTarget],
        root: Path,
        *,
        on_result=None,
    ) -> list[ReputationPageResult | Exception]: ...

    def close(self) -> None: ...
