"""短期服务器浏览器认证任务和 WebSocket 中继。"""

from __future__ import annotations

import asyncio
import base64
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from patchright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)

from .collectors import AuthenticationRequired, CollectorFailure, DongchediCollector
from .config import Settings
from .errors import DomainError
from .ids import uuid7
from .session_store import SessionStore
from .worker import WorkerService


@dataclass
class AuthTask:
    id: str
    platform_code: str
    ticket: str
    expires_at: datetime
    status: str = "created"
    error_message: str | None = None
    claimed: bool = False
    playwright: Playwright | None = None
    browser: Browser | None = None
    context: BrowserContext | None = None
    page: Page | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class BrowserAuthManager:
    """认证任务不接收或持久化账号密码，只中继用户对官方页面的输入。"""

    def __init__(self, settings: Settings, session_store: SessionStore, worker: WorkerService):
        self.settings = settings
        self.session_store = session_store
        self.worker = worker
        self.tasks: dict[str, AuthTask] = {}

    async def create(self, platform_code: str) -> dict[str, Any]:
        if platform_code != "dongchedi":
            raise DomainError(
                "PLATFORM_NOT_INTEGRATED", "该平台暂未接入认证流程。", status_code=409
            )
        await self.cleanup_expired()
        active = next(
            (
                task
                for task in self.tasks.values()
                if task.platform_code == platform_code
                and task.status in {"created", "active"}
                and task.expires_at > datetime.now(timezone.utc)
            ),
            None,
        )
        task = active or AuthTask(
            id=uuid7(),
            platform_code=platform_code,
            ticket=secrets.token_urlsafe(32),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        )
        self.tasks[task.id] = task
        return self.task_dict(task)

    def get(self, task_id: str) -> dict[str, Any]:
        task = self.tasks.get(task_id)
        if not task:
            raise DomainError(
                "AUTH_TASK_NOT_FOUND", "平台认证任务不存在或已经过期。", status_code=404
            )
        return self.task_dict(task)

    @staticmethod
    def task_dict(task: AuthTask) -> dict[str, Any]:
        status_names = {
            "created": "已创建",
            "active": "认证中",
            "completed": "已完成",
            "failed": "失败",
            "expired": "已过期",
            "cancelled": "已结束",
        }
        return {
            "id": task.id,
            "platform_code": task.platform_code,
            "status": task.status,
            "status_name": status_names.get(task.status, task.status),
            "expires_at": task.expires_at,
            "error_message": task.error_message,
            "ticket": task.ticket if task.status in {"created", "active"} else None,
            "websocket_path": f"/api/v1/auth/tasks/{task.id}/stream",
        }

    async def _ensure_browser(self, task: AuthTask) -> Page:
        if task.page and not task.page.is_closed():
            return task.page
        task.playwright = await async_playwright().start()
        task.browser = await task.playwright.chromium.launch(
            headless=self.settings.auth_browser_headless
        )
        current = self.session_store.get_state(task.platform_code)
        context_args = {
            "viewport": {"width": 1280, "height": 800},
            "locale": "zh-CN",
            "timezone_id": self.settings.timezone,
        }
        if current:
            context_args["storage_state"] = current
        task.context = await task.browser.new_context(**context_args)
        task.page = await task.context.new_page()
        await task.page.goto(
            "https://www.dongchedi.com/community/24729",
            wait_until="domcontentloaded",
            timeout=60_000,
        )
        task.status = "active"
        return task.page

    async def stream(self, task_id: str, ticket: str, websocket: WebSocket) -> None:
        task = self.tasks.get(task_id)
        if (
            not task
            or not secrets.compare_digest(task.ticket, ticket)
            or task.expires_at <= datetime.now(timezone.utc)
        ):
            await websocket.close(code=4404, reason="认证任务不存在或已经过期")
            return
        await websocket.accept()
        async with task.lock:
            try:
                page = await self._ensure_browser(task)
                await websocket.send_json(
                    {"type": "ready", "width": 1280, "height": 800, "url": page.url}
                )
                while task.status == "active" and datetime.now(timezone.utc) < task.expires_at:
                    try:
                        command = await asyncio.wait_for(websocket.receive_json(), timeout=0.7)
                        await self._command(task, command, websocket)
                    except asyncio.TimeoutError:
                        image = await page.screenshot(type="jpeg", quality=70)
                        await websocket.send_json(
                            {
                                "type": "frame",
                                "data": base64.b64encode(image).decode("ascii"),
                                "url": page.url,
                            }
                        )
            except WebSocketDisconnect:
                # 连接断开只关闭本次入口，浏览器保留到任务到期，允许重新打开。
                return
            except Exception as exc:
                task.status = "failed"
                task.error_message = f"平台认证浏览器运行失败：{exc}"
                try:
                    await websocket.send_json({"type": "error", "message": task.error_message})
                except Exception:
                    pass

    async def _command(self, task: AuthTask, command: dict[str, Any], websocket: WebSocket) -> None:
        page = task.page
        if not page:
            return
        kind = command.get("type")
        if kind == "click":
            await page.mouse.click(float(command.get("x", 0)), float(command.get("y", 0)))
        elif kind == "type":
            # 输入只送往当前官方页面焦点，不写日志或数据库。
            await page.keyboard.type(str(command.get("text", "")))
        elif kind == "key":
            await page.keyboard.press(str(command.get("key", "Enter")))
        elif kind == "scroll":
            await page.mouse.wheel(float(command.get("dx", 0)), float(command.get("dy", 0)))
        elif kind == "finish":
            if not task.context:
                return
            state = await task.context.storage_state()
            try:
                await asyncio.to_thread(
                    DongchediCollector(state, concurrency=1).validate_circle,
                    "https://www.dongchedi.com/community/24729",
                )
            except (AuthenticationRequired, CollectorFailure) as exc:
                task.error_message = f"平台认证状态校验未通过：{exc}"
                await websocket.send_json(
                    {"type": "validation_failed", "message": task.error_message}
                )
                return
            self.session_store.import_state(task.platform_code, state)
            self.worker.resume_platform(task.platform_code)
            task.status = "completed"
            await websocket.send_json(
                {"type": "completed", "message": "平台会话已更新，等待任务将自动续跑。"}
            )
            await self._close(task)
        elif kind == "close":
            await websocket.close(code=1000)

    async def cleanup_expired(self) -> None:
        now = datetime.now(timezone.utc)
        for task in list(self.tasks.values()):
            if task.expires_at <= now and task.status in {"created", "active"}:
                task.status = "expired"
                await self._close(task)

    async def _close(self, task: AuthTask) -> None:
        if task.context:
            await task.context.close()
            task.context = None
            task.page = None
        if task.browser:
            await task.browser.close()
            task.browser = None
        if task.playwright:
            await task.playwright.stop()
            task.playwright = None

    async def close_all(self) -> None:
        for task in self.tasks.values():
            await self._close(task)

    async def close_platform(self, platform_code: str) -> None:
        """用户结束认证等待时，同步关闭该平台的临时交互入口。"""

        for task in self.tasks.values():
            if task.platform_code == platform_code and task.status in {
                "created",
                "active",
            }:
                task.status = "cancelled"
                await self._close(task)
