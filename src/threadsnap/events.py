"""单进程状态变化事件总线，SSE 只负责通知前端回查 HTTP。"""

from __future__ import annotations

import threading
from collections import deque
from datetime import datetime, timezone
from typing import Any


class EventBus:
    """保存有限事件窗口，并允许 SSE 连接按序号等待新事件。"""

    def __init__(self, capacity: int = 1000):
        self._condition = threading.Condition()
        self._sequence = 0
        self._events: deque[dict[str, Any]] = deque(maxlen=capacity)

    def publish(self, event_type: str, resource_id: str = "", **summary: Any) -> dict[str, Any]:
        with self._condition:
            self._sequence += 1
            event = {
                "id": self._sequence,
                "type": event_type,
                "resource_id": resource_id,
                "summary_version": summary.pop("summary_version", None),
                "summary": summary,
                "occurred_at": datetime.now(timezone.utc).isoformat(),
            }
            self._events.append(event)
            self._condition.notify_all()
            return event

    def wait_after(self, sequence: int, timeout: float = 20.0) -> list[dict[str, Any]]:
        with self._condition:
            available = [item for item in self._events if item["id"] > sequence]
            if available:
                return available
            self._condition.wait(timeout)
            return [item for item in self._events if item["id"] > sequence]
