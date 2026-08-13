"""平台采集器注册表。"""

from .dongchedi import AuthenticationRequired, CollectorFailure, DongchediCollector

__all__ = ["AuthenticationRequired", "CollectorFailure", "DongchediCollector"]
