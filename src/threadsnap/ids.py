"""领域标识生成。"""

from __future__ import annotations

import secrets
import threading
import time
import uuid

_lock = threading.Lock()
_last_ms = 0
_sequence = 0


def uuid7() -> str:
    """生成按毫秒大致有序的 UUIDv7 字符串。"""

    global _last_ms, _sequence
    with _lock:
        now_ms = int(time.time() * 1000)
        if now_ms == _last_ms:
            _sequence = (_sequence + 1) & 0x0FFF
        else:
            _last_ms = now_ms
            _sequence = secrets.randbits(12)
        rand_b = secrets.randbits(62)
        value = (now_ms & ((1 << 48) - 1)) << 80
        value |= 0x7 << 76
        value |= (_sequence & 0x0FFF) << 64
        value |= 0x2 << 62
        value |= rand_b
        return str(uuid.UUID(int=value))
