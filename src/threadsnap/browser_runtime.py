"""浏览器运行时参数。"""

from __future__ import annotations

import os


def browser_launch_args() -> list[str]:
    """在无头 Wayland 合成器中让完整 Chromium 使用原生 Wayland。"""

    if os.environ.get("WAYLAND_DISPLAY"):
        return ["--ozone-platform=wayland"]
    return []
