"""单进程业务使用租约与短时排他清理门。"""

from __future__ import annotations

import asyncio
import threading
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Iterator

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class ActivityLease:
    """可跨线程归还且重复归还安全的业务租约。"""

    def __init__(self, owner: StorageActivity) -> None:
        self.owner = owner
        self.released = False

    def release(self) -> None:
        """仅第一次归还减少使用者计数，不依赖取得租约的线程。"""
        with self.owner._lock:
            if not self.released:
                self.owner._users -= 1
                self.released = True


class StorageActivity:
    """允许多个业务操作并行；清理仅在没有在途操作时取得排他权。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._users = 0
        self._maintaining = False

    def try_acquire(self) -> ActivityLease | None:
        """立即取得使用租约；已有清理时返回空，不阻塞后台线程。"""
        with self._lock:
            if self._maintaining:
                return None
            self._users += 1
            return ActivityLease(self)

    @contextmanager
    def use(self) -> Iterator[bool]:
        """后台操作的作用域；未取得租约时调用方应在下一轮再试。"""
        lease = self.try_acquire()
        try:
            yield lease is not None
        finally:
            if lease:
                lease.release()

    @contextmanager
    def maintenance(self) -> Iterator[bool]:
        """非阻塞取得排他权；失败不能执行任何删除。"""
        with self._lock:
            acquired = not self._maintaining and self._users == 0
            if acquired:
                self._maintaining = True
        try:
            yield acquired
        finally:
            if acquired:
                with self._lock:
                    self._maintaining = False


class StorageProcessLock:
    """后端与停服维护命令共用OS文件锁，避免另一进程绕过内存租约。"""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.stream: Any = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stream = self.path.open("a+b")
        try:
            if stream.seek(0, 2) == 0:
                stream.write(b"\0")
                stream.flush()
            stream.seek(0)
            import os
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            stream.close()
            raise RuntimeError("业务后端或另一维护进程仍在使用此数据目录，请先停止它。") from exc
        self.stream = stream

    def release(self) -> None:
        if self.stream:
            self.stream.close()
            self.stream = None

    def __enter__(self) -> StorageProcessLock:
        self.acquire()
        return self

    def __exit__(self, *args: Any) -> None:
        self.release()


def storage_operation(idle_result: Any = None) -> Callable:
    """给现有后台入口附加可选租约，不改变直接使用服务的测试/脚本合同。"""
    def decorate(method: Callable) -> Callable:
        @wraps(method)
        def guarded(self: Any, *args: Any, **kwargs: Any) -> Any:
            activity = getattr(self, "storage_activity", None)
            if activity is None:
                return method(self, *args, **kwargs)
            with activity.use() as acquired:
                if not acquired:
                    return idle_result
                return method(self, *args, **kwargs)

        return guarded

    return decorate


class StorageActivityMiddleware:
    """租约覆盖完整ASGI响应（包括文件发送/断开），SSE长连接除外。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        protected = scope["type"] == "http" and path.startswith(("/api/v1", "/internal/v1"))
        if not protected or path.rstrip("/") == "/api/v1/events":
            await self.app(scope, receive, send)
            return
        container = getattr(scope["app"].state, "container", None)
        activity = getattr(container, "storage_activity", None)
        if activity is None:
            await self.app(scope, receive, send)
            return
        # 普通API与下载可并行。明确删除请求也须排他，避免删除正在传输的文件。
        if scope.get("method") == "DELETE":
            for _ in range(100):
                with activity.maintenance() as acquired:
                    if acquired:
                        await self.app(scope, receive, send)
                        return
                await asyncio.sleep(0.05)
        else:
            for _ in range(100):
                lease = activity.try_acquire()
                if lease:
                    try:
                        await self.app(scope, receive, send)
                    finally:
                        lease.release()
                    return
                await asyncio.sleep(0.05)
        response = JSONResponse(
            status_code=503,
            content={
                "code": "STORAGE_BUSY",
                "message": "后台业务或数据清理正在进行，请稍后重试。",
                "details": [],
            },
            headers={"Retry-After": "1"},
        )
        await response(scope, receive, send)
