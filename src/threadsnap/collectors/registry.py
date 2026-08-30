"""平台适配器能力注册表；业务层只依赖本模块，不识别平台私有类型。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .autohome import (
    ADAPTER_VERSION as AUTOHOME_VERSION,
)
from .autohome import (
    AutohomeCollector,
)
from .autohome import (
    normalize_post_url as normalize_autohome_post_url,
)
from .autohome import (
    parse_circle_url as parse_autohome_circle_url,
)
from .base import CircleSource, Collector, CollectorFailure
from .dongchedi import (
    ADAPTER_VERSION as DONGCHEDI_VERSION,
)
from .dongchedi import (
    DongchediCollector,
)
from .dongchedi import (
    normalize_post_url as normalize_dongchedi_post_url,
)
from .dongchedi import (
    parse_circle_url as parse_dongchedi_circle_url,
)
from .yiche import ADAPTER_VERSION as YICHE_VERSION
from .yiche import YicheCollector
from .yiche import normalize_post_url as normalize_yiche_post_url
from .yiche import parse_circle_url as parse_yiche_circle_url

CollectorFactory = Callable[..., Collector]
CircleParser = Callable[[str], CircleSource]
PostNormalizer = Callable[[str], tuple[str, str]]


@dataclass(frozen=True)
class PlatformAdapterSpec:
    """平台注册、运行能力和输入合同的单一事实入口。"""

    code: str
    display_name: str
    adapter_status: str
    adapter_version: str | None
    collector_factory: CollectorFactory | None
    parse_circle_url: CircleParser | None
    normalize_post_url: PostNormalizer | None
    default_enabled: bool = False
    default_concurrency: int = 1
    min_quantity: int = 1
    max_quantity: int = 2000
    min_concurrency: int = 1
    max_concurrency: int = 1
    supports_authentication: bool = False
    authentication_mode: str = "none"
    supports_page_evidence: bool = False
    supports_live_video_resolution: bool = False
    background_transport: str = "direct_http"
    login_url: str | None = None
    auth_probe_circle_url: str | None = None
    auth_url_markers: tuple[str, ...] = ()

    def create_collector(
        self,
        storage_state: dict[str, Any] | None,
        *,
        concurrency: int,
        browser_headless: bool,
    ) -> Collector:
        """根据能力声明创建适配器；可运行性仍由数据库状态门禁。"""

        if self.collector_factory is None:
            raise CollectorFailure("PLATFORM_NOT_INTEGRATED", f"{self.display_name}暂未接入。")
        return self.collector_factory(
            storage_state,
            concurrency=concurrency,
            browser_headless=browser_headless,
        )

    def create_background_collector(
        self,
        storage_state: dict[str, Any] | None,
        *,
        concurrency: int,
    ) -> Collector:
        """后台采集固定使用直连传输；浏览器只属于人工认证或显式页面证据。"""

        return self.create_collector(
            storage_state,
            concurrency=concurrency,
            browser_headless=False,
        )


PLATFORM_ADAPTERS: dict[str, PlatformAdapterSpec] = {
    "dongchedi": PlatformAdapterSpec(
        code="dongchedi",
        display_name="懂车帝",
        adapter_status="available",
        adapter_version=DONGCHEDI_VERSION,
        collector_factory=DongchediCollector,
        parse_circle_url=parse_dongchedi_circle_url,
        normalize_post_url=normalize_dongchedi_post_url,
        default_enabled=True,
        default_concurrency=2,
        max_concurrency=8,
        supports_authentication=True,
        authentication_mode="account_login",
        supports_page_evidence=True,
        supports_live_video_resolution=True,
        login_url=("https://www.dongchedi.com/login-required?redirect=%2Fcommunity%2F24729"),
        auth_probe_circle_url="https://www.dongchedi.com/community/24729",
        auth_url_markers=("/login-required",),
    ),
    "autohome": PlatformAdapterSpec(
        code="autohome",
        display_name="汽车之家",
        # 本地适配器与公共业务链已完成，平台注册为可用；正式 500/500 继续作为生产验收。
        adapter_status="available",
        adapter_version=AUTOHOME_VERSION,
        collector_factory=AutohomeCollector,
        parse_circle_url=parse_autohome_circle_url,
        normalize_post_url=normalize_autohome_post_url,
        max_concurrency=8,
        supports_authentication=True,
        authentication_mode="account_login",
        supports_page_evidence=False,
        supports_live_video_resolution=True,
        login_url=(
            "https://account.autohome.com.cn/?backurl=https%3A%2F%2Fclub.autohome.com.cn%2F"
        ),
        auth_probe_circle_url="https://club.autohome.com.cn/bbs/forum-c-7853-1.html?sort=post",
        auth_url_markers=("account.autohome.com.cn",),
    ),
    "yiche": PlatformAdapterSpec(
        code="yiche",
        display_name="易车",
        # 适配器与公共业务链已经交付，平台注册为可用；是否创建任务仍由 enabled 控制。
        adapter_status="available",
        adapter_version=YICHE_VERSION,
        collector_factory=YicheCollector,
        parse_circle_url=parse_yiche_circle_url,
        normalize_post_url=normalize_yiche_post_url,
        max_quantity=500,
        max_concurrency=8,
        supports_authentication=True,
        authentication_mode="account_login",
        supports_page_evidence=False,
        supports_live_video_resolution=False,
        login_url=(
            "https://i.yiche.com/authenservice/login.html?returnurl=https%3A%2F%2Fbaa.yiche.com%2F"
        ),
        auth_probe_circle_url="https://baa.yiche.com/ruihu8/index-0-0-1.html",
        auth_url_markers=("i.yiche.com/authenservice/login",),
    ),
}


def get_platform_spec(code: str) -> PlatformAdapterSpec:
    """返回平台注册项；未知平台使用稳定领域错误。"""

    try:
        return PLATFORM_ADAPTERS[code]
    except KeyError as exc:
        raise CollectorFailure("PLATFORM_NOT_FOUND", "指定平台不存在。") from exc


def platform_specs() -> tuple[PlatformAdapterSpec, ...]:
    """按稳定平台代码顺序返回所有平台注册项。"""

    return tuple(PLATFORM_ADAPTERS[code] for code in sorted(PLATFORM_ADAPTERS))


def get_acceptance_provider(code: str) -> Any | None:
    """返回独立验收桥；不读取或改变平台注册的接入状态。"""

    if code != "autohome":
        return None
    from .autohome_acceptance import create_autohome_acceptance_provider

    return create_autohome_acceptance_provider()
