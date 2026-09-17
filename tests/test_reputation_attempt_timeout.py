"""只验证执行项总预算、取消后的槽位归还和 HTTP 剩余预算，不请求真实平台。"""

from __future__ import annotations

import asyncio
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from threadsnap.reputation_adapter import ReputationAdapterError, ReputationMappingTarget
from threadsnap.reputation_autohome import AutohomeReputationAdapter
from threadsnap.reputation_browser import (
    acquire_global_slot,
    attempt_stage,
    attempt_timeout,
    bounded_http_thread,
    check_access_response,
)
from threadsnap.reputation_dongchedi import DongchediReputationAdapter
from threadsnap.reputation_yiche import YicheReputationAdapter


class _StalledPage:
    """让真实适配器导航停滞，只有外层执行项截止时间能结束。"""

    def set_default_timeout(self, timeout):
        pass

    def on(self, event, callback):
        pass

    async def goto(self, *args, **kwargs):
        await asyncio.sleep(10)


class _Browser:
    """记录真实适配器的上下文清理，不启动 Chromium。"""

    def __init__(self):
        self.contexts_closed = 0

    async def new_context(self, **kwargs):
        async def new_page():
            return _StalledPage()

        async def close():
            self.contexts_closed += 1

        return SimpleNamespace(new_page=new_page, close=close)

    async def close(self):
        pass


class _Playwright:
    def __init__(self, browser):
        self.browser = browser

    async def __aenter__(self):
        async def launch(**kwargs):
            return self.browser

        return SimpleNamespace(chromium=SimpleNamespace(launch=launch))

    async def __aexit__(self, *args):
        pass


class ReputationAttemptTimeoutTests(unittest.IsolatedAsyncioTestCase):
    async def test_three_platform_attempts_end_and_release_slot_after_deadline(self):
        """三平台实际 validate→_visit 均在导航挂起时终止，排队时间不侵占单项预算。"""

        cases = [
            (AutohomeReputationAdapter, "https://k.autohome.com.cn/1/", "reputation_browser"),
            (YicheReputationAdapter, "https://dianping.yiche.com/car/koubei/", "reputation_browser"),
            (DongchediReputationAdapter, "https://www.dongchedi.com/auto/series/1", "reputation_dongchedi"),
        ]
        with tempfile.TemporaryDirectory() as temporary:
            for adapter_class, url, module in cases:
                with self.subTest(platform=adapter_class.code):
                    limiter = threading.BoundedSemaphore(1)
                    limiter.acquire()
                    browser = _Browser()
                    adapter = adapter_class(None, timeout_seconds=0.04, global_limiter=limiter)
                    target = ReputationMappingTarget("vehicle", "1", url, "车型", "hash")
                    callbacks = []

                    async def release_queue():
                        await asyncio.sleep(0.06)
                        limiter.release()

                    release = asyncio.create_task(release_queue())
                    started = time.monotonic()
                    try:
                        with patch(
                            f"threadsnap.{module}.async_playwright",
                            return_value=_Playwright(browser),
                        ):
                            result = await adapter.validate(
                                [target], Path(temporary) / adapter.code,
                                on_result=lambda *args: callbacks.append(args),
                            )
                    finally:
                        await release
                        adapter.close()
                    elapsed = time.monotonic() - started
                    self.assertGreaterEqual(elapsed, 0.09)
                    self.assertLess(elapsed, 0.7)
                    self.assertEqual(result[0].code, "REPUTATION_ITEM_TIMEOUT")
                    self.assertTrue(result[0].retryable)
                    self.assertIn("页面导航", str(result[0]))
                    self.assertEqual(len(callbacks), 1)
                    self.assertEqual(browser.contexts_closed, 1)
                    self.assertTrue(limiter.acquire(blocking=False))
                    limiter.release()

    async def test_cancelled_waiters_do_not_steal_global_capacity(self):
        """批次取消等槽位协程后，不会遗留线程再占掉两个巡检槽位。"""

        limiter = threading.BoundedSemaphore(2)
        limiter.acquire()
        limiter.acquire()
        waiters = [asyncio.create_task(acquire_global_slot(limiter)) for _ in range(3)]
        await asyncio.sleep(0.02)
        for task in waiters:
            task.cancel()
        await asyncio.gather(*waiters, return_exceptions=True)
        limiter.release()
        limiter.release()
        for status, code in ((401, "AUTH_REQUIRED"), (403, "AUTH_REQUIRED"), (429, "PLATFORM_RATE_LIMITED")):
            with self.subTest(status=status), self.assertRaises(ReputationAdapterError) as raised:
                check_access_response(SimpleNamespace(status=status))
            self.assertEqual(code, raised.exception.code)
        await asyncio.sleep(0.06)
        self.assertTrue(limiter.acquire(blocking=False))
        self.assertTrue(limiter.acquire(blocking=False))
        self.assertFalse(limiter.acquire(blocking=False))
        limiter.release()
        limiter.release()

    async def test_http_uses_remaining_budget_and_drains_before_slot_release(self):
        """同步接口只得到页面消费后的余额；取消须等有界请求退出再归还槽位。"""

        adapter = DongchediReputationAdapter(None, timeout_seconds=90)
        target = ReputationMappingTarget("vehicle", "1", "https://example.test/1", "车型", "hash")
        timeouts = []
        finished = threading.Event()
        limiter = threading.BoundedSemaphore(1)

        def get(*args, timeout, **kwargs):
            timeouts.append(timeout)
            time.sleep(timeout + 0.02)
            finished.set()
            raise TimeoutError("模拟有界 HTTP 超时")

        started = time.monotonic()
        await acquire_global_slot(limiter)
        try:
            with patch.object(adapter, "_http_session", return_value=SimpleNamespace(get=get)):
                with self.assertRaises(ReputationAdapterError) as raised:
                    async with attempt_timeout(0.07):
                        await asyncio.sleep(0.035)
                        attempt_stage("读取差评率接口")
                        await bounded_http_thread(adapter._visit_negative_rate, target)
            self.assertTrue(finished.is_set())
            self.assertFalse(limiter.acquire(blocking=False))
        finally:
            limiter.release()
            adapter.close()
        self.assertEqual(raised.exception.code, "REPUTATION_ITEM_TIMEOUT")
        self.assertIn("读取差评率接口", str(raised.exception))
        self.assertGreater(timeouts[0], 0)
        self.assertLess(timeouts[0], 0.04)
        self.assertLess(time.monotonic() - started, 0.5)
        self.assertTrue(limiter.acquire(blocking=False))
        limiter.release()
