"""平台采集器公共合同与注册表。"""

from .autohome import AutohomeCollector
from .base import AuthenticationRequired, Collector, CollectorFailure
from .dongchedi import DongchediCollector
from .registry import PlatformAdapterSpec, get_platform_spec, platform_specs

__all__ = [
    "AuthenticationRequired",
    "AutohomeCollector",
    "Collector",
    "CollectorFailure",
    "DongchediCollector",
    "PlatformAdapterSpec",
    "get_platform_spec",
    "platform_specs",
]
