"""服务启动固定标准事件循环，避免依赖存在与否改变驱动子进程路径。"""

import unittest
from unittest.mock import patch

from threadsnap import cli


class CliEventLoopTests(unittest.TestCase):
    def test_serve_uses_standard_loop_and_preserves_host_port(self) -> None:
        with (
            patch("sys.argv", ["threadsnap", "serve", "--host", "127.0.0.1", "--port", "8765"]),
            patch.object(cli.uvicorn, "run") as run,
        ):
            cli.main()
        run.assert_called_once_with(
            "threadsnap.app:app", host="127.0.0.1", port=8765, reload=False, loop="asyncio"
        )
