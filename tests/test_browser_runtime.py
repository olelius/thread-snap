"""浏览器显示后端参数测试。"""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from threadsnap.browser_runtime import browser_launch_args


class BrowserRuntimeTests(unittest.TestCase):
    def test_desktop_environment_keeps_default_browser_arguments(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual([], browser_launch_args())

    def test_wayland_environment_selects_native_wayland(self) -> None:
        with patch.dict(os.environ, {"WAYLAND_DISPLAY": "wayland-99"}, clear=True):
            self.assertEqual(["--ozone-platform=wayland"], browser_launch_args())


if __name__ == "__main__":
    unittest.main()
