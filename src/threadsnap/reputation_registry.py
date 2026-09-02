"""垂媒口碑巡检平台注册表。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from . import reputation_autohome, reputation_dongchedi, reputation_yiche


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


REPUTATION_PLATFORMS: dict[str, ReputationPlatformSpec] = {
    "dongchedi": ReputationPlatformSpec(
        "dongchedi",
        "懂车帝",
        reputation_dongchedi.DongchediReputationAdapter,
        reputation_dongchedi.normalize_series_url,
        reputation_dongchedi.ADAPTER_VERSION,
        reputation_dongchedi.VALIDATION_CONTRACT_VERSION,
        reputation_dongchedi.VIEWPORT,
    ),
    "autohome": ReputationPlatformSpec(
        "autohome",
        "汽车之家",
        reputation_autohome.AutohomeReputationAdapter,
        reputation_autohome.normalize_series_url,
        reputation_autohome.ADAPTER_VERSION,
        reputation_autohome.VALIDATION_CONTRACT_VERSION,
        reputation_autohome.VIEWPORT,
    ),
    "yiche": ReputationPlatformSpec(
        "yiche",
        "易车",
        reputation_yiche.YicheReputationAdapter,
        reputation_yiche.normalize_series_url,
        reputation_yiche.ADAPTER_VERSION,
        reputation_yiche.VALIDATION_CONTRACT_VERSION,
        reputation_yiche.VIEWPORT,
    ),
}


def require_reputation_platform(code: str) -> ReputationPlatformSpec:
    """取得已接入口碑平台；未知代码由调用方转换为领域错误。"""

    return REPUTATION_PLATFORMS[code.strip().lower()]
