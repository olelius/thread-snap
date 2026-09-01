"""短期服务器浏览器认证任务、隔离 Profile 和 WebSocket 中继。"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import secrets
import shutil
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

from cryptography.fernet import Fernet, InvalidToken
from fastapi import WebSocket, WebSocketDisconnect
from patchright.async_api import (
    BrowserContext,
    CDPSession,
    Page,
    Playwright,
    async_playwright,
)
from patchright.async_api import Error as PlaywrightError
from sqlalchemy import select

from .browser_runtime import browser_launch_args
from .collectors import (
    CollectorFailure,
    get_platform_spec,
)
from .config import Settings
from .errors import DomainError
from .ids import uuid7
from .models import CircleTask, PlatformConfig
from .session_store import SessionStore
from .worker import WorkerService

logger = logging.getLogger(__name__)

INTERACTIVE_RECOVERY_CODES = {"PLATFORM_CAPTCHA_REQUIRED", "PLATFORM_CHALLENGE"}


class AuthPageLoadError(RuntimeError):
    """认证页面未形成可操作 DOM。"""

    def __init__(self, code: str, message: str, *, http_status: int | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


class AuthProfileStore:
    """以任务临时目录运行 Profile，并仅加密持久化正式副本。"""

    TRANSIENT_FILES = {
        "DevToolsActivePort",
        "SingletonCookie",
        "SingletonLock",
        "SingletonSocket",
    }

    def __init__(self, root: Path, fernet: Fernet):
        self.root = root.resolve()
        self.fernet = fernet
        self.root.mkdir(parents=True, exist_ok=True)
        self.cleanup_stale_tasks()

    def cleanup_stale_tasks(self) -> None:
        """单进程服务启动时清除上次异常退出遗留的任务明文目录。"""

        for platform_root in self.root.iterdir():
            if not platform_root.is_dir():
                continue
            shutil.rmtree(platform_root / "tasks", ignore_errors=True)
            for pending in platform_root.glob(".*.profile.enc.tmp"):
                pending.unlink(missing_ok=True)

    def prepare(
        self, platform_code: str, task_id: str, *, inherit_current: bool = True
    ) -> Path:
        profile = self.root / platform_code / "tasks" / task_id
        if profile.exists():
            shutil.rmtree(profile)
        profile.mkdir(parents=True, mode=0o700)
        encrypted = self.current(platform_code)
        if inherit_current and encrypted.is_file():
            try:
                payload = self.fernet.decrypt(encrypted.read_bytes())
                with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                    for member in archive.infolist():
                        target = (profile / member.filename).resolve()
                        if not target.is_relative_to(profile.resolve()):
                            raise ValueError("浏览器 Profile 压缩包包含越界路径。")
                    archive.extractall(profile)
            except (InvalidToken, OSError, ValueError, zipfile.BadZipFile) as exc:
                shutil.rmtree(profile, ignore_errors=True)
                raise AuthPageLoadError(
                    "AUTH_PROFILE_DECRYPT_FAILED",
                    "服务器浏览器 Profile 读取失败，请检查认证密钥或清理损坏的 Profile。",
                ) from exc
        try:
            os.chmod(profile, 0o700)
        except OSError:
            pass
        return profile

    def current(self, platform_code: str) -> Path:
        return self.root / platform_code / "current.profile.enc"

    def promote(self, platform_code: str, source: Path, task_id: str) -> Path:
        """加密并原子替换正式 Profile，成功后清理任务明文目录。"""

        source = source.resolve()
        if not source.is_dir() or not source.is_relative_to(self.root):
            raise ValueError("认证临时 Profile 不存在或超出认证目录。")
        platform_root = self.root / platform_code
        platform_root.mkdir(parents=True, exist_ok=True)
        current = self.current(platform_code)
        pending = platform_root / f".{task_id}.profile.enc.tmp"
        try:
            buffer = io.BytesIO()
            with zipfile.ZipFile(
                buffer,
                mode="w",
                compression=zipfile.ZIP_DEFLATED,
                compresslevel=3,
            ) as archive:
                for path in source.rglob("*"):
                    if not path.is_file() or path.is_symlink() or path.name in self.TRANSIENT_FILES:
                        continue
                    archive.write(path, path.relative_to(source).as_posix())
            pending.write_bytes(self.fernet.encrypt(buffer.getvalue()))
            try:
                os.chmod(pending, 0o600)
            except OSError:
                pass
            pending.replace(current)
        except Exception:
            pending.unlink(missing_ok=True)
            raise
        shutil.rmtree(source)
        return current

    def discard(self, profile: Path | None) -> None:
        if not profile:
            return
        resolved = profile.resolve()
        if resolved.is_relative_to(self.root) and resolved.exists():
            shutil.rmtree(resolved)


@dataclass
class AuthTask:
    id: str
    platform_code: str
    ticket: str
    expires_at: datetime
    status: str = "created"
    page_status: str = "pending"
    error_code: str | None = None
    error_message: str | None = None
    http_status: int | None = None
    fresh_profile: bool = False
    start_url: str | None = None
    run_id: str | None = None
    recovery_error_code: str | None = None
    interactive_control_seen: bool = False
    playwright: Playwright | None = None
    context: BrowserContext | None = None
    page: Page | None = None
    profile_dir: Path | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class BrowserAuthManager:
    """认证任务不接收或持久化账号密码，只中继用户对官方页面的输入。"""

    def __init__(
        self,
        settings: Settings,
        session_store: SessionStore,
        worker: WorkerService,
        event_publisher: Callable[..., Any] | None = None,
    ):
        self.settings = settings
        self.session_store = session_store
        self.worker = worker
        self.event_publisher = event_publisher
        self.profiles = AuthProfileStore(settings.auth_profile_dir, session_store.fernet)
        self.tasks: dict[str, AuthTask] = {}

    async def create(
        self,
        platform_code: str,
        *,
        fresh: bool = False,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        try:
            spec = get_platform_spec(platform_code)
        except CollectorFailure as exc:
            raise DomainError(exc.code, exc.message, status_code=404) from exc
        if not spec.supports_authentication or not spec.login_url:
            raise DomainError(
                "PLATFORM_NOT_INTEGRATED", "该平台暂未接入认证流程。", status_code=409
            )
        start_url = spec.login_url
        recovery_error_code: str | None = None
        with self.worker.factory() as db:
            platform = db.get(PlatformConfig, platform_code)
            if not platform or platform.adapter_status != "available":
                raise DomainError(
                    "PLATFORM_NOT_INTEGRATED",
                    "该平台尚未通过正式可用门，当前不能创建认证任务。",
                    status_code=409,
                )
            if run_id:
                waiting = db.scalar(
                    select(CircleTask)
                    .where(
                        CircleTask.run_id == run_id,
                        CircleTask.platform_code == platform_code,
                        CircleTask.status == "waiting_for_auth",
                    )
                    .order_by(CircleTask.queue_sequence)
                )
                if not waiting:
                    raise DomainError(
                        "RUN_AUTH_TASK_NOT_FOUND",
                        "该批次当前没有此平台的待处理会话任务。",
                        status_code=409,
                    )
                recovery_error_code = waiting.error_code
                trigger_url = str(
                    (waiting.checkpoint or {}).get("trigger_url") or waiting.circle_url
                )
                # 验证码和访问验证必须继承当前已登录 Profile；全新环境会丢失登录态，
                # 把原本的验证恢复错误地变成 AUTH_REQUIRED。
                if recovery_error_code in INTERACTIVE_RECOVERY_CODES:
                    start_url = trigger_url
                    fresh = False
                elif recovery_error_code == "AUTH_REQUIRED":
                    # 真正的登录失效才进入官方登录页；公开帖子页本身不能完成登录恢复。
                    start_url = spec.login_url
                else:
                    start_url = trigger_url
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
        if active and (
            fresh
            or active.start_url != start_url
            or active.run_id != run_id
            or active.recovery_error_code != recovery_error_code
        ):
            active.status = "cancelled"
            active.page_status = "cancelled"
            await self._close(active)
            active = None
        task = active or AuthTask(
            id=uuid7(),
            platform_code=platform_code,
            ticket=secrets.token_urlsafe(32),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
            fresh_profile=fresh,
            start_url=start_url,
            run_id=run_id,
            recovery_error_code=recovery_error_code,
        )
        self.tasks[task.id] = task
        return self.task_dict(task)

    def get(self, task_id: str) -> dict[str, Any]:
        task = self.tasks.get(task_id)
        if not task:
            raise DomainError(
                "AUTH_TASK_NOT_FOUND", "平台会话任务不存在或已经过期。", status_code=404
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
            "page_status": task.page_status,
            "expires_at": task.expires_at,
            "error_code": task.error_code,
            "error_message": task.error_message,
            "http_status": task.http_status,
            "fresh_profile": task.fresh_profile,
            "recovery_error_code": task.recovery_error_code,
            "ticket": task.ticket if task.status in {"created", "active"} else None,
            "websocket_path": f"/api/v1/auth/tasks/{task.id}/stream",
        }

    async def _ensure_browser(self, task: AuthTask) -> Page:
        if task.page and not task.page.is_closed() and task.page_status == "ready":
            return task.page
        task.page_status = "starting"
        task.profile_dir = self.profiles.prepare(
            task.platform_code,
            task.id,
            inherit_current=not task.fresh_profile,
        )
        task.playwright = await async_playwright().start()
        task.context = await task.playwright.chromium.launch_persistent_context(
            user_data_dir=str(task.profile_dir),
            headless=self.settings.auth_browser_headless,
            args=browser_launch_args(),
            viewport={"width": 1280, "height": 800},
            locale="zh-CN",
            timezone_id=self.settings.timezone,
        )
        task.page = task.context.pages[0] if task.context.pages else await task.context.new_page()
        task.page_status = "loading"
        response = await task.page.goto(
            task.start_url or get_platform_spec(task.platform_code).login_url,
            wait_until="domcontentloaded",
            timeout=60_000,
        )
        task.http_status = response.status if response else None
        await self._require_interactive_page(task.page, response)
        task.status = "active"
        task.page_status = "ready"
        task.error_code = None
        task.error_message = None
        return task.page

    @staticmethod
    async def _require_interactive_page(page: Page, response: Any) -> None:
        """拒绝平台返回的零字节文档和不可操作空 DOM。"""

        status = response.status if response else None
        headers = await response.all_headers() if response else {}
        if status is not None and status >= 400:
            raise AuthPageLoadError(
                "AUTH_PAGE_HTTP_ERROR",
                f"平台会话页面返回 HTTP {status}。",
                http_status=status,
            )
        if headers.get("content-length", "").strip() == "0":
            raise AuthPageLoadError(
                "AUTH_PAGE_EMPTY",
                "平台向当前服务器浏览器返回了零字节空页面，请重新创建认证浏览器。",
                http_status=status,
            )
        html = ""
        body_text = ""
        controls = 0
        for _ in range(10):
            html = await page.content()
            body_text = await page.locator("body").inner_text(timeout=2_000)
            controls = await page.locator("input,button,iframe,a").count()
            if len(html) > 200 and (body_text.strip() or controls > 0):
                return
            await page.wait_for_timeout(500)
        raise AuthPageLoadError(
            "AUTH_PAGE_EMPTY_DOM",
            "平台会话页面没有形成可操作内容，请重新创建会话浏览器。",
            http_status=status,
        )

    async def stream(self, task_id: str, ticket: str, websocket: WebSocket) -> None:
        task = self.tasks.get(task_id)
        if (
            not task
            or not secrets.compare_digest(task.ticket, ticket)
            or task.expires_at <= datetime.now(timezone.utc)
        ):
            await websocket.close(code=4404, reason="认证任务不存在或已经过期")
            return
        await websocket.accept(subprotocol="threadsnap-auth")
        async with task.lock:
            try:
                await websocket.send_json({"type": "browser_starting"})
                page = await self._ensure_browser(task)
                await websocket.send_json(
                    {
                        "type": "ready",
                        "width": 1280,
                        "height": 800,
                        "url": page.url,
                        "page_status": task.page_status,
                    }
                )
                self._observe_interactive_control(task, page.url)
                cdp = await task.context.new_cdp_session(page)
                frame_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1)

                async def acknowledge_discarded_frame(frame: dict[str, Any]) -> None:
                    try:
                        await cdp.send(
                            "Page.screencastFrameAck",
                            {"sessionId": frame["sessionId"]},
                        )
                    except Exception:
                        pass

                def receive_frame(frame: dict[str, Any]) -> None:
                    # CDP 要求逐帧确认；队列只保留一个待发送帧，避免客户端变慢时堆积旧画面。
                    if frame_queue.full():
                        asyncio.create_task(acknowledge_discarded_frame(frame))
                        return
                    frame_queue.put_nowait(frame)

                cdp.on("Page.screencastFrame", receive_frame)
                await cdp.send("Page.enable")
                await cdp.send(
                    "Page.startScreencast",
                    {
                        "format": "jpeg",
                        "quality": 85,
                        "maxWidth": 1280,
                        "maxHeight": 800,
                        "everyNthFrame": 1,
                    },
                )
                receive_task = asyncio.create_task(websocket.receive_json())
                frame_task = asyncio.create_task(frame_queue.get())
                while task.status == "active":
                    remaining_seconds = (
                        task.expires_at - datetime.now(timezone.utc)
                    ).total_seconds()
                    if remaining_seconds <= 0:
                        break
                    done, _ = await asyncio.wait(
                        {receive_task, frame_task},
                        timeout=min(remaining_seconds, 1.0),
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if not done:
                        continue
                    if receive_task in done:
                        command = receive_task.result()
                        await self._command(task, command, websocket, cdp)
                        if command.get("type") == "close" or task.status != "active":
                            break
                        receive_task = asyncio.create_task(websocket.receive_json())
                    if frame_task in done and task.status == "active":
                        frame = frame_task.result()
                        if self._observe_interactive_control(task, page.url):
                            await self._command(task, {"type": "finish"}, websocket, cdp)
                            if task.status != "active":
                                break
                        await websocket.send_json(
                            {
                                "type": "frame",
                                "data": frame["data"],
                                "url": page.url,
                                "page_status": task.page_status,
                            }
                        )
                        await cdp.send(
                            "Page.screencastFrameAck",
                            {"sessionId": frame["sessionId"]},
                        )
                        frame_task = asyncio.create_task(frame_queue.get())
                if task.status == "active" and task.expires_at <= datetime.now(timezone.utc):
                    task.status = "expired"
                    task.page_status = "expired"
                    await self._close(task)
            except WebSocketDisconnect:
                # 连接断开只关闭本次入口，浏览器保留到任务到期，允许重新打开。
                return
            except AuthPageLoadError as exc:
                task.status = "failed"
                task.page_status = "failed"
                task.error_code = exc.code
                task.error_message = exc.message
                task.http_status = exc.http_status
                try:
                    await websocket.send_json(
                        {
                            "type": "page_failed",
                            "code": exc.code,
                            "message": exc.message,
                            "http_status": exc.http_status,
                        }
                    )
                except Exception:
                    pass
                await self._close(task)
            except Exception as exc:
                task.status = "failed"
                task.page_status = "failed"
                task.error_code = "AUTH_BROWSER_FAILED"
                task.error_message = f"平台会话浏览器运行失败：{exc}"
                try:
                    await websocket.send_json(
                        {
                            "type": "error",
                            "code": task.error_code,
                            "message": task.error_message,
                        }
                    )
                except Exception:
                    pass
                await self._close(task)
            finally:
                for pending in (locals().get("receive_task"), locals().get("frame_task")):
                    if pending and not pending.done():
                        pending.cancel()
                active_cdp = locals().get("cdp")
                if active_cdp:
                    try:
                        await active_cdp.send("Page.stopScreencast")
                    except Exception:
                        pass
                    try:
                        await active_cdp.detach()
                    except Exception:
                        pass

    @staticmethod
    def _observe_interactive_control(task: AuthTask, current_url: str) -> bool:
        """记录验证页出现，并在其回到原站页面后请求自动保存与续跑。"""

        if task.recovery_error_code not in INTERACTIVE_RECOVERY_CODES:
            return False
        parsed = urlsplit(current_url)
        host = (parsed.hostname or "").lower()
        normalized = current_url.lower()
        control_visible = (
            host == "safety.autohome.com.cn"
            or "userverify" in normalized
            or "captcha" in normalized
            or "challenge" in normalized
        )
        if control_visible:
            task.interactive_control_seen = True
            return False
        if not task.interactive_control_seen:
            return False
        expected_host = (urlsplit(task.start_url or "").hostname or "").lower()
        if not host or not expected_host:
            return False
        return host == expected_host or host.endswith(f".{expected_host}") or expected_host.endswith(
            f".{host}"
        )

    async def _command(
        self,
        task: AuthTask,
        command: dict[str, Any],
        websocket: WebSocket,
        cdp: CDPSession | None = None,
    ) -> None:
        page = task.page
        if not page:
            return
        kind = command.get("type")
        if kind == "click":
            if cdp:
                await self._dispatch_pointer(cdp, "mousePressed", command)
                await self._dispatch_pointer(cdp, "mouseReleased", command)
            else:
                await page.mouse.click(float(command.get("x", 0)), float(command.get("y", 0)))
        elif kind == "pointer_move" and cdp:
            await self._dispatch_pointer(cdp, "mouseMoved", command)
        elif kind == "pointer_down" and cdp:
            await self._dispatch_pointer(cdp, "mousePressed", command)
        elif kind == "pointer_up" and cdp:
            await self._dispatch_pointer(cdp, "mouseReleased", command)
        elif kind == "type":
            # 输入只送往当前官方页面焦点，不写日志或数据库。
            if cdp:
                await cdp.send("Input.insertText", {"text": str(command.get("text", ""))})
            else:
                await page.keyboard.insert_text(str(command.get("text", "")))
        elif kind == "key":
            await page.keyboard.press(str(command.get("key", "Enter")))
        elif kind == "key_down":
            await page.keyboard.down(str(command.get("key", "")))
        elif kind == "key_up":
            await page.keyboard.up(str(command.get("key", "")))
        elif kind == "scroll":
            if cdp:
                await self._dispatch_pointer(cdp, "mouseWheel", command)
            else:
                await page.mouse.wheel(float(command.get("dx", 0)), float(command.get("dy", 0)))
        elif kind == "finish":
            if not task.context or not task.profile_dir:
                return
            spec = get_platform_spec(task.platform_code)
            access_session = spec.authentication_mode == "access_session"
            session_label = "访问会话" if access_session else "登录 Session"
            environment_label = "访问环境" if access_session else "登录环境"
            task.page_status = "validating"
            await websocket.send_json({"type": "validating", "message": "正在保存平台 Session…"})
            state = await task.context.storage_state()
            try:
                # 在关闭浏览器前检查导出结构；Cookie 空值是合法状态，不属于结构错误。
                self.session_store.validate_state(state)
            except DomainError:
                logger.error("平台认证浏览器导出的会话结构无效：platform=%s", task.platform_code)
                task.page_status = "ready"
                task.error_code = "AUTH_SESSION_STATE_INVALID"
                task.error_message = (
                    f"平台{session_label}结构异常，请使用全新{environment_label}重新处理。"
                )
                await websocket.send_json(
                    {
                        "type": "validation_failed",
                        "code": task.error_code,
                        "message": task.error_message,
                    }
                )
                return

            # 人工认证入口只负责导出并保存服务器浏览器 Session，不把当前页面 URL、
            # 圈子、帖子、点赞或其他采集端点的判断混入“保存 Session”操作。真实
            # 采集门禁由 Worker 在原 URL 上执行并按平台错误类型恢复。

            try:
                previous_state = self.session_store.get_state(task.platform_code)
                profile_dir = task.profile_dir
                await self._close_browser(task)
                self.session_store.import_state(task.platform_code, state)
                try:
                    self.profiles.promote(task.platform_code, profile_dir, task.id)
                except Exception:
                    if previous_state:
                        self.session_store.import_state(task.platform_code, previous_state)
                    else:
                        self.session_store.clear(task.platform_code)
                    raise
            except Exception as exc:
                logger.error(
                    "平台认证会话持久化失败：platform=%s type=%s",
                    task.platform_code,
                    type(exc).__name__,
                )
                task.status = "failed"
                task.page_status = "failed"
                task.error_code = "AUTH_SESSION_SAVE_FAILED"
                task.error_message = (
                    f"平台{session_label}已导出，但保存失败，请重新创建会话浏览器。"
                )
                await websocket.send_json(
                    {
                        "type": "session_save_failed",
                        "code": task.error_code,
                        "message": task.error_message,
                    }
                )
                return
            task.profile_dir = None
            self.worker.resume_platform(task.platform_code)
            if self.event_publisher:
                self.event_publisher("session.changed", task.platform_code, status="valid")
            task.status = "completed"
            task.page_status = "completed"
            task.error_code = None
            task.error_message = None
            await websocket.send_json(
                {
                    "type": "completed",
                    "message": "平台 Session 已保存；等待任务将按原 URL 恢复并执行实际采集检查。",
                }
            )
        elif kind == "close":
            await websocket.close(code=1000)

    @staticmethod
    async def _dispatch_pointer(
        cdp: CDPSession,
        event_type: str,
        command: dict[str, Any],
    ) -> None:
        """把认证画布坐标和指针状态映射为受控 Chromium 的 CDP 输入事件。"""

        button = str(command.get("button", "left"))
        if button not in {"none", "left", "middle", "right", "back", "forward"}:
            button = "none"
        payload: dict[str, Any] = {
            "type": event_type,
            "x": max(0.0, min(1280.0, float(command.get("x", 0)))),
            "y": max(0.0, min(800.0, float(command.get("y", 0)))),
            "modifiers": max(0, min(15, int(command.get("modifiers", 0)))),
        }
        if event_type == "mouseWheel":
            payload.update(
                {
                    "deltaX": float(command.get("dx", 0)),
                    "deltaY": float(command.get("dy", 0)),
                    "buttons": max(0, min(31, int(command.get("buttons", 0)))),
                }
            )
        else:
            payload.update(
                {
                    "button": button,
                    "buttons": max(0, min(31, int(command.get("buttons", 0)))),
                    "clickCount": max(0, min(2, int(command.get("click_count", 0)))),
                }
            )
        await cdp.send("Input.dispatchMouseEvent", payload)

    async def cleanup_expired(self) -> None:
        now = datetime.now(timezone.utc)
        for task in list(self.tasks.values()):
            if task.expires_at <= now and task.status in {"created", "active"}:
                task.status = "expired"
                task.page_status = "expired"
                await self._close(task)

    async def _close_browser(self, task: AuthTask) -> None:
        context = task.context
        task.context = None
        task.page = None
        if context:
            try:
                await context.close()
            except PlaywrightError as exc:
                if "has been closed" not in str(exc):
                    raise
        playwright = task.playwright
        task.playwright = None
        if playwright:
            await playwright.stop()

    async def _close(self, task: AuthTask) -> None:
        await self._close_browser(task)
        self.profiles.discard(task.profile_dir)
        task.profile_dir = None

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
                task.page_status = "cancelled"
                await self._close(task)
