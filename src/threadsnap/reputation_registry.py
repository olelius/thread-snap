"""垂媒口碑巡检平台注册表。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from . import reputation_autohome, reputation_dongchedi, reputation_yiche

CORE_METRIC_KEYS = ("score", "rank", "volume", "review_article_count", "negative_rate")
METRIC_LABELS = {
    "score": "口碑分",
    "rank": "排名",
    "volume": "口碑量",
    "review_article_count": "口碑评价篇数",
    "negative_rate": "差评率",
    "circle_content_count": "圈内内容数",
}


def metric_label(platform_code: str, key: str) -> str:
    """共用计数字段在不同平台保留各自业务名称。"""
    if platform_code == "autohome" and key == "circle_content_count":
        return "论坛帖子总数"
    return METRIC_LABELS[key]


@dataclass(frozen=True)
class ReputationPlatformSpec:
    """一个口碑平台的稳定代码、适配器和验证合同。"""

    code: str
    display_name: str
    adapter_factory: Callable[..., Any]
    normalize_url: Callable[[str, str | None], str]
    adapter_version: str
    validation_contract_version: str
    viewport: dict[str, int]
    requires_session: bool = True
    requires_evidence: bool = True
    metric_keys: tuple[str, ...] = CORE_METRIC_KEYS


REPUTATION_PLATFORMS: dict[str, ReputationPlatformSpec] = {
    "dongchedi": ReputationPlatformSpec(
        "dongchedi",
        "懂车帝",
        reputation_dongchedi.DongchediReputationAdapter,
        reputation_dongchedi.normalize_series_url,
        reputation_dongchedi.ADAPTER_VERSION,
        reputation_dongchedi.VALIDATION_CONTRACT_VERSION,
        reputation_dongchedi.VIEWPORT,
        metric_keys=(*CORE_METRIC_KEYS, "circle_content_count"),
    ),
    "autohome": ReputationPlatformSpec(
        "autohome",
        "汽车之家",
        reputation_autohome.AutohomeReputationAdapter,
        reputation_autohome.normalize_series_url,
        reputation_autohome.ADAPTER_VERSION,
        reputation_autohome.VALIDATION_CONTRACT_VERSION,
        reputation_autohome.VIEWPORT,
        metric_keys=tuple(key for key in CORE_METRIC_KEYS if key != "negative_rate") + ("circle_content_count",),
    ),
    "yiche": ReputationPlatformSpec(
        "yiche",
        "易车",
        reputation_yiche.YicheReputationAdapter,
        reputation_yiche.normalize_series_url,
        reputation_yiche.ADAPTER_VERSION,
        reputation_yiche.VALIDATION_CONTRACT_VERSION,
        reputation_yiche.VIEWPORT,
        requires_session=False,
        requires_evidence=False,
        metric_keys=tuple(key for key in CORE_METRIC_KEYS if key != "negative_rate"),
    ),
}


def require_reputation_platform(code: str) -> ReputationPlatformSpec:
    """取得已接入口碑平台；未知代码由调用方转换为领域错误。"""

    return REPUTATION_PLATFORMS[code.strip().lower()]
