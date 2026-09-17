"""汽车之家与易车口碑页共用的有界浏览器执行骨架。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import threading
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager, suppress
from contextvars import ContextVar
from pathlib import Path
from time import monotonic
from typing import Any, Awaitable, Callable

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


_SETTLE_SAMPLE_LIMIT = 13
_SETTLE_CONSECUTIVE = 3
_GEOMETRY_EPSILON = 1.0


def _rect_edges(rect: Any) -> tuple[float, float, float, float] | None:
    """解析有限、正面积的文档坐标矩形；返回左、上、右、下四条边。"""

    if not isinstance(rect, dict):
        return None
    try:
        x, y, width, height = (float(rect[key]) for key in ("x", "y", "width", "height"))
    except (KeyError, TypeError, ValueError):
        return None
    if not all(math.isfinite(value) for value in (x, y, width, height, x + width, y + height)):
        return None
    if x < 0 or y < 0 or width <= 0 or height <= 0:
        return None
    return x, y, x + width, y + height


def _settled_geometry(
    samples: list[dict[str, Any]], keys: tuple[str, ...]
) -> dict[str, dict[str, float]] | None:
    """三次矩形每条边的总极差至多 1px；外扩取整并保持已知文档边界。"""

    merged: dict[str, dict[str, float]] = {}
    for key in keys:
        edges = [_rect_edges(sample.get(key)) for sample in samples]
        if any(rect is None for rect in edges):
            return None
        concrete = [rect for rect in edges if rect is not None]
        if any(max(edge[i] for edge in concrete) - min(edge[i] for edge in concrete) >
               _GEOMETRY_EPSILON for i in range(4)):
            return None
        left = math.floor(min(edge[0] for edge in concrete))
        top = math.floor(min(edge[1] for edge in concrete))
        right = math.ceil(max(edge[2] for edge in concrete))
        bottom = math.ceil(max(edge[3] for edge in concrete))
        for sample, edge in zip(samples, concrete):
            # 已知文档边界必须有效；不把越界截图裁小成貌似成功的证据。
            for field, maximum in (("document_width", edge[2]), ("document_height", edge[3])):
                if field not in sample:
                    continue
                try:
                    bound = float(sample[field])
                except (TypeError, ValueError):
                    return None
                if not math.isfinite(bound) or bound <= 0 or maximum > bound:
                    return None
        # 页面边缘可能是小数：保留可用文档边界，不让取整多伸出半像素。
        last = samples[-1]
        if "document_width" in last:
            right = min(right, float(last["document_width"]))
        if "document_height" in last:
            bottom = min(bottom, float(last["document_height"]))
        if right < max(edge[2] for edge in concrete) or bottom < max(edge[3] for edge in concrete):
            return None
        merged[key] = {"x": left, "y": top, "width": right - left, "height": bottom - top}
    return merged


def _content_stable(samples: list[dict[str, Any]], keys: tuple[str, ...]) -> bool:
    """身份必须存在；指标允许平台明确缺省，但选定字段仍逐项严格比较。"""

    if len(samples) != _SETTLE_CONSECUTIVE or not keys:
        return False
    if any(not isinstance(sample.get("actual_name"), str) or
           not sample["actual_name"].strip() for sample in samples):
        return False
    return all(
        all(sample.get(key) == samples[0].get(key) for key in keys)
        for sample in samples[1:]
    )


async def settle_measure(
    measure: Callable[[], Awaitable[dict[str, Any] | None]],
    *,
    content_keys: tuple[str, ...] = ("actual_name", "score", "rank", "volume"),
    geometry_keys: tuple[str, ...] = ("rect",),
    geometry_required: bool = True,
    window_seconds: float = 3.0,
    interval_seconds: float = 0.25,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """同页有界等待连续三次稳定；只比较核心内容和各边总漂移，不要求全页静止。

    返回最终安全包围矩形及有限原始采样。失败实例携带 measurements 和
    metrics_stable；调用方仅在身份、接口合同另行通过时保留已稳定的数据。
    """

    budget = remaining_timeout(max(0.001, window_seconds))
    # 给外层执行项计时器保留极短的诊断抛出余量，不另起采集预算。
    expires = monotonic() + max(0.0, budget - min(0.005, budget / 10))
    samples: list[dict[str, Any]] = []
    while len(samples) < _SETTLE_SAMPLE_LIMIT:
        remaining = expires - monotonic()
        if remaining <= 0:
            break
        try:
            value = await asyncio.wait_for(measure(), timeout=remaining)
        except TimeoutError:
            samples.append({"measurement_error": "测量调用超时"})
            break
        except ReputationAdapterError as error:
            # 明确的平台访问条件或身份错误不被稳定等待吞掉，附带此前测量供定位。
            error.measurements = samples[-_SETTLE_SAMPLE_LIMIT:]
            error.metrics_stable = False
            error.geometry_stable = False
            raise
        except Exception as error:
            # DOM 重建时 evaluate 可能暂时失败；作为无效采样重置连续窗口。
            value = {"measurement_error": type(error).__name__}
        # 缺失节点也是一次失败采样，重置连续窗口而不是跨过空档凑三次。
        sample = dict(value) if isinstance(value, dict) else {"measurement_error": "节点尚未出现"}
        samples.append(sample)
        tail = samples[-_SETTLE_CONSECUTIVE:]
        if _content_stable(tail, content_keys):
            geometry = _settled_geometry(tail, geometry_keys) if geometry_required else {}
            if geometry is not None:
                return {**sample, **geometry}, samples
        remaining = expires - monotonic()
        if remaining <= 0:
            break
        await asyncio.sleep(min(max(0.001, interval_seconds), remaining))

    tail = samples[-_SETTLE_CONSECUTIVE:]
    metrics_stable = _content_stable(tail, content_keys)
    geometry_stable = (
        len(tail) == _SETTLE_CONSECUTIVE
        and (not geometry_required or _settled_geometry(tail, geometry_keys) is not None)
    )
    message = (
        "页面指标已稳定，但截图边界仍在变化或无效。"
        if metrics_stable else "页面身份或口碑指标在等待窗口内尚未稳定。"
    )
    error = ReputationAdapterError("REPUTATION_PAGE_UNSTABLE", message, retryable=True)
    error.measurements = samples
    error.metrics_stable = metrics_stable
    error.geometry_stable = geometry_stable
    error.layout_only = metrics_stable and not geometry_stable
    raise error


async def stable_measure(
    page, script: str, *, geometry_required: bool = True
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """冻结 CSS 动态效果后复用有界采样；URL 模式只要求身份和指标稳定。"""

    await page.add_style_tag(
        content="*,*::before,*::after{animation:none!important;transition:none!important;}"
    )
    return await settle_measure(lambda: page.evaluate(script), geometry_required=geometry_required)


async def capture_region(page, path: Path, rect: dict[str, Any]) -> tuple[int, int, str]:
    """按冻结文档坐标保存唯一指标区域 PNG。"""

    if _rect_edges(rect) is None:
        raise ReputationAdapterError("REPUTATION_EVIDENCE_REGION_MISSING", "指标区域边界无效。")
    clip = {name: float(rect[name]) for name in ("x", "y", "width", "height")}
    # 先于整项取消返回截图失败，调用方才能保留已取得的可靠指标。
    budget = min(5.0, remaining_timeout(5.0))
    await asyncio.wait_for(
        page.screenshot(path=str(path), clip=clip, animations="disabled"),
        timeout=max(0.001, budget - 0.01),
    )
    from PIL import Image

    with Image.open(path) as image:
        image.load()
        width, height = image.size
    if abs(width - clip["width"]) > 1 or abs(height - clip["height"]) > 1:
        raise ReputationAdapterError("REPUTATION_EVIDENCE_WRITE_FAILED", "截图尺寸与采样区域不一致。")
    return width, height, sha256(path)


def evidence_failure(error: Exception) -> ReputationAdapterError:
    """截图阶段错误单独分类；不把浏览器原始异常中的查询参数写入诊断。"""

    if isinstance(error, ReputationAdapterError):
        return error
    return ReputationAdapterError(
        "REPUTATION_EVIDENCE_WRITE_FAILED",
        f"指标已经取得，但截图生成失败：{type(error).__name__}。",
        retryable=True,
    )


def record_measurements(
    output_dir: Path, target: ReputationMappingTarget,
    measurements: list[dict[str, Any]], error: ReputationAdapterError | None = None,
) -> None:
    """保存有限的公开指标/几何诊断，供一次失败或成功的采集追溯。"""

    # 不记录整页HTML、Cookie、请求头或接口响应，只保存稳定门的公开字段。
    keys = {"actual_name", "score", "rank", "volume", "score_raw", "rank_raw", "volume_raw",
            "review_article_count_raw", "rank_scope", "rect", "heading_box", "score_box",
            "volume_box", "rank_box", "availability_box", "document_width", "document_height",
            "measurement_error"}
    samples = [{k: v for k, v in row.items() if k in keys} for row in measurements[-13:]]
    path = output_dir / f"{target.vehicle_id}-layout.json"
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "vehicle_id": target.vehicle_id, "measurements": samples,
            "error_code": error.code if error else None,
            "error_message": error.message if error else None,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        # 证据磁盘写入失败时，诊断文件也可能失败；不能再抹掉已确认指标。
        logging.getLogger(__name__).warning("口碑布局诊断文件写入失败。")


def elapsed_ms(started: float) -> int:
    """返回适配器单项耗时。"""

    return round((monotonic() - started) * 1000)
