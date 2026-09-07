"""口碑共用浏览器启动合同：无头复用完整 Chromium，有头参数保持不变。"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from threadsnap.reputation_adapter import ReputationMappingTarget
from threadsnap.reputation_autohome import AutohomeReputationAdapter
from threadsnap.reputation_yiche import YicheReputationAdapter


class BrowserLaunchTests(unittest.IsolatedAsyncioTestCase):
    """覆盖两种显示模式的公共验证入口，不访问平台或生成业务数据。"""

    async def _assert_launch(self, adapter, *, headless, channel):
        """验证启动选项、单项回调与关闭行为，隔离平台页面解析。"""

        target = ReputationMappingTarget(
            "fixture", "100", "https://example.test/100/", "测试车型", "fixture-hash"
        )
        result = Mock()
        adapter._visit = AsyncMock(return_value=result)
        browser = Mock()
        browser.close = AsyncMock()
        runtime = Mock()
        runtime.chromium.launch = AsyncMock(return_value=browser)
        callback = Mock()
        launch_args = ["--ozone-platform=wayland"]

        with (
            tempfile.TemporaryDirectory() as temp,
            patch("threadsnap.reputation_browser.async_playwright") as factory,
            patch("threadsnap.reputation_browser.browser_launch_args", return_value=launch_args),
        ):
            factory.return_value.__aenter__.return_value = runtime
            output_dir = Path(temp) / "results"
            results = await adapter.validate([target], output_dir, on_result=callback)

            runtime.chromium.launch.assert_awaited_once_with(
                headless=headless, channel=channel, args=launch_args
            )
            adapter._visit.assert_awaited_once_with(browser, target, output_dir)
            callback.assert_called_once_with(0, target, result)
            self.assertEqual([result], results)
            self.assertTrue(output_dir.is_dir())
        browser.close.assert_awaited_once_with()

    async def test_yiche_headless_uses_packaged_full_chromium(self):
        """易车即使收到旧有头选项，仍以完整 Chromium 无头执行。"""

        await self._assert_launch(
            YicheReputationAdapter(None, headless=False), headless=True, channel="chromium"
        )

    async def test_autohome_headed_keeps_default_browser_selection(self):
        """汽车之家默认有头模式保留原默认浏览器和 Wayland 参数。"""

        await self._assert_launch(AutohomeReputationAdapter(None), headless=False, channel=None)

    async def test_explicit_headless_uses_shared_full_chromium_contract(self):
        """公共适配器的显式无头路径使用同一离线浏览器选择规则。"""

        await self._assert_launch(
            AutohomeReputationAdapter(None, headless=True), headless=True, channel="chromium"
        )
