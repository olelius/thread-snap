"""汽车之家与易车口碑页共用的有界浏览器执行骨架。"""

from __future__ import annotations

import asyncio
import hashlib
from abc import ABC, abstractmethod
from pathlib import Path
from time import monotonic
from typing import Any, Callable

from patchright.async_api import Browser, async_playwright

from .browser_runtime import browser_launch_args
from .reputation_adapter import (
    ReputationAdapterError,
    ReputationMappingTarget,
    ReputationPageResult,
)


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
        **_: Any,
    ) -> None:
        self.storage_state = storage_state
        self.concurrency = max(1, min(int(concurrency), 8))
        self.headless = headless
        self.timeout_seconds = max(1, int(timeout_seconds))
        self.batch_timeout_seconds = max(1, int(batch_timeout_seconds))
        self.evidence_policy = evidence_policy

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
        on_result: Callable[
            [int, ReputationMappingTarget, ReputationPageResult | Exception], None
        ]
        | None = None,
    ) -> list[ReputationPageResult | Exception]:
        """按输入顺序返回；单项完成时立即通过回调持久化。"""

        output_dir.mkdir(parents=True, exist_ok=False)
        semaphore = asyncio.Semaphore(self.concurrency)
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(
                headless=self.headless,
                args=browser_launch_args(),
            )

            async def bounded(index: int, target: ReputationMappingTarget):
                async with semaphore:
                    try:
                        result: ReputationPageResult | Exception = await self._visit(
                            browser, target, output_dir
                        )
                    except Exception as error:  # 单项错误必须留在本批次结果中
                        result = error
                if on_result:
                    on_result(index, target, result)
                return result

            tasks = [
                asyncio.create_task(bounded(index, target))
                for index, target in enumerate(targets)
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
        raise ReputationAdapterError(
            "REPUTATION_EVIDENCE_REGION_MISSING", "指标区域边界无效。"
        )
    await page.screenshot(path=str(path), clip=clip, animations="disabled")
    from PIL import Image

    with Image.open(path) as image:
        width, height = image.size
    return width, height, sha256(path)


def elapsed_ms(started: float) -> int:
    """返回适配器单项耗时。"""

    return round((monotonic() - started) * 1000)
