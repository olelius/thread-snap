"""汽车之家与易车口碑页共用的有界浏览器执行骨架。"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import threading
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager, suppress
from contextvars import ContextVar
from pathlib import Path
from time import monotonic
from typing import Any, Callable

from patchright.async_api import Browser, async_playwright
from patchright.async_api import TimeoutError as BrowserTimeoutError

from .browser_runtime import browser_launch_args
from .reputation_adapter import (
    ReputationAdapterError,
    ReputationMappingTarget,
    ReputationPageResult,
)

_attempt_deadline: ContextVar[float | None] = ContextVar("reputation_attempt_deadline", default=None)
_attempt_stage: ContextVar[str] = ContextVar("reputation_attempt_stage", default="访问页面")


def attempt_stage(stage: str) -> None:
    """记录当前协程的采集阶段，供超时诊断使用，不在并发执行项之间共享。"""

    _attempt_stage.set(stage)


def check_access_response(response) -> None:
    """明确的认证或限流响应要求先恢复访问条件，不反复请求。"""

    if response is None:
        return
    status = getattr(response, "status", getattr(response, "status_code", None))
    if status in {401, 403}:
        raise ReputationAdapterError("AUTH_REQUIRED", "平台要求先恢复认证或访问权限。")
    if status == 429:
        raise ReputationAdapterError("PLATFORM_RATE_LIMITED", "平台请求频率受限，请冷却后补跑。")


def remaining_timeout(default_seconds: float) -> float:
    """返回当前执行项剩余预算；同步 HTTP 线程继承调用方的截止时间。"""

    deadline = _attempt_deadline.get()
    remaining = default_seconds if deadline is None else min(default_seconds, deadline - monotonic())
    if remaining <= 0:
        raise ReputationAdapterError(
            "REPUTATION_ITEM_TIMEOUT", "口碑执行项已达到采集时限。", retryable=True
        )
    return remaining


@asynccontextmanager
async def attempt_timeout(timeout_seconds: float):
    """取得执行槽位后启动整项预算；导航、指标请求和截图共享一个截止时间。"""

    token = _attempt_deadline.set(monotonic() + timeout_seconds)
    stage_token = _attempt_stage.set("创建页面上下文")
    timer = asyncio.timeout(timeout_seconds)
    try:
        async with timer:
            yield
    except (TimeoutError, BrowserTimeoutError) as error:
        raise ReputationAdapterError(
            "REPUTATION_ITEM_TIMEOUT",
            f"口碑执行项在{_attempt_stage.get()}阶段超时（本次采集预算{timeout_seconds:g}秒）。",
            retryable=True,
        ) from error
    finally:
        _attempt_deadline.reset(token)
        _attempt_stage.reset(stage_token)


async def acquire_global_slot(limiter: threading.Semaphore | None) -> None:
    """可取消地等候跨线程共享槽位，避免后台阻塞 acquire 在取消后偷偷占用容量。"""

    if limiter is not None:
        while not limiter.acquire(blocking=False):
            await asyncio.sleep(0.05)


async def bounded_http_thread(function, *args, **kwargs):
    """取消时先收拢已开始的有界 HTTP 请求，再允许调用方释放全局槽位。"""

    task = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        # HTTP 本身使用 remaining_timeout，退出不会额外获得一份完整单项预算。
        # 单项和批次截止可能连续取消；始终保留槽位直到已开始的线程请求真正退出。
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        with suppress(Exception):
            task.result()
        raise


async def close_context(context) -> None:
    """取消或错误后有界回收上下文，清理失败不覆盖原始业务错误。"""

    try:
        await asyncio.wait_for(context.close(), timeout=3)
    except Exception:
        logging.getLogger(__name__).warning("口碑页面上下文有界回收失败。", exc_info=True)


def sha256(path: Path) -> str:
    """流式计算证据文件摘要。"""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class BrowserReputationAdapter(ABC):
    """为只需浏览器路径的平台提供固定并发、超时和回调语义。"""

    viewport = {"width": 1440, "height": 1000}

    def __init__(
        self,
        storage_state: dict[str, Any] | None,
        *,
        concurrency: int = 2,
        headless: bool = False,
        timeout_seconds: int = 90,
        batch_timeout_seconds: int = 45 * 60,
        evidence_policy=None,
        global_limiter: threading.Semaphore | None = None,
        **_: Any,
    ) -> None:
        self.storage_state = storage_state
        self.concurrency = max(1, min(int(concurrency), 8))
        self.headless = headless
        self.timeout_seconds = max(0.001, float(timeout_seconds))
        self.batch_timeout_seconds = max(1, int(batch_timeout_seconds))
        self.evidence_policy = evidence_policy
        self.global_limiter = global_limiter

    async def _acquire_global_slot(self) -> None:
        """跨平台共享正式巡检页面并发槽位，避免线程事件循环各自放大并发。"""

        await acquire_global_slot(self.global_limiter)

    def _release_global_slot(self) -> None:
        if self.global_limiter is not None:
            self.global_limiter.release()

    def close(self) -> None:
        """浏览器生命周期在单次验证内关闭；保留统一关闭接口。"""

    @abstractmethod
    async def _visit(
        self,
        browser: Browser,
        target: ReputationMappingTarget,
        output_dir: Path,
    ) -> ReputationPageResult:
        """访问一个映射并返回冻结结果。"""

    async def validate(
        self,
        targets: list[ReputationMappingTarget],
        output_dir: Path,
        on_result: Callable[[int, ReputationMappingTarget, ReputationPageResult | Exception], None]
        | None = None,
    ) -> list[ReputationPageResult | Exception]:
        """按输入顺序返回；单项完成时立即通过回调持久化。"""

        output_dir.mkdir(parents=True, exist_ok=False)
        semaphore = asyncio.Semaphore(self.concurrency)
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(
                headless=self.headless,
                # 离线包仅含完整 Chromium；无头模式也复用它，不查找 headless shell。
                channel="chromium" if self.headless else None,
                args=browser_launch_args(),
            )

            async def bounded(index: int, target: ReputationMappingTarget):
                async with semaphore:
                    await self._acquire_global_slot()
                    try:
                        async with attempt_timeout(self.timeout_seconds):
                            result: ReputationPageResult | Exception = await self._visit(
                                browser, target, output_dir
                            )
                    except Exception as error:  # 单项错误必须留在本批次结果中
                        result = error
                    finally:
                        self._release_global_slot()
                if on_result:
                    on_result(index, target, result)
                return result

            tasks = [
                asyncio.create_task(bounded(index, target)) for index, target in enumerate(targets)
            ]
            done, pending = await asyncio.wait(
                tasks,
                timeout=self.batch_timeout_seconds,
                return_when=asyncio.ALL_COMPLETED,
            )
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            timeout_error = ReputationAdapterError(
                "REPUTATION_BATCH_TIMEOUT", "口碑巡检达到批次时限，未完成项已结束。"
            )
            if on_result:
                for index, task in enumerate(tasks):
                    if task not in done:
                        on_result(index, targets[index], timeout_error)
            await browser.close()
            return [task.result() if task in done else timeout_error for task in tasks]

    def validate_sync(
        self,
        targets: list[ReputationMappingTarget],
        output_dir: Path,
        on_result=None,
    ) -> list[ReputationPageResult | Exception]:
        """同步路由与后台执行器入口。"""

        return asyncio.run(self.validate(targets, output_dir, on_result=on_result))


async def stable_measure(page, script: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """冻结动态效果后，要求指标与矩形连续三次一致。"""

    await page.add_style_tag(
        content="*,*::before,*::after{animation:none!important;transition:none!important;}"
    )
    measurements: list[dict[str, Any]] = []
    for _ in range(3):
        measurement = await page.evaluate(script)
        if not isinstance(measurement, dict):
            raise ReputationAdapterError(
                "REPUTATION_METRICS_MISSING", "页面没有形成可验证的口碑指标。", retryable=True
            )
        measurements.append(measurement)
        await page.wait_for_timeout(250)
    keys = [
        (
            item.get("actual_name"),
            item.get("score"),
            item.get("rank"),
            item.get("volume"),
            item.get("rect"),
        )
        for item in measurements
    ]
    if len({repr(item) for item in keys}) != 1:
        raise ReputationAdapterError(
            "REPUTATION_PAGE_UNSTABLE", "页面身份、指标或截图边界尚未稳定。", retryable=True
        )
    return measurements[-1], measurements


async def capture_region(page, path: Path, rect: dict[str, Any]) -> tuple[int, int, str]:
    """按冻结文档坐标保存唯一指标区域 PNG。"""

    clip = {name: float(rect[name]) for name in ("x", "y", "width", "height")}
    if clip["width"] <= 0 or clip["height"] <= 0:
        raise ReputationAdapterError("REPUTATION_EVIDENCE_REGION_MISSING", "指标区域边界无效。")
    await page.screenshot(path=str(path), clip=clip, animations="disabled")
    from PIL import Image

    with Image.open(path) as image:
        width, height = image.size
    return width, height, sha256(path)


def elapsed_ms(started: float) -> int:
    """返回适配器单项耗时。"""

    return round((monotonic() - started) * 1000)
