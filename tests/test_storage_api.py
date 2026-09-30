"""防止ASGI中间件顺序使实际文件发送提前失去保留租约。"""

import asyncio
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from threadsnap.app import create_app
from threadsnap.config import Settings
from threadsnap.storage_activity import StorageProcessLock


class PausedTransport:
    """在最外层发送处暂停，不替换应用FileResponse或生命周期中间件。"""

    def __init__(self, app, position):
        self.app = app
        self.position = position
        self.started = threading.Event()
        self.release = threading.Event()

    async def __call__(self, scope, receive, send):
        async def held(message):
            if (
                scope.get("path") == "/api/v1/page-evidence/transport/image"
                and message["type"] == "http.response.body"
                and (self.position == "first" or not message.get("more_body", False))
                and not self.started.is_set()
            ):
                self.started.set()
                if not await asyncio.to_thread(self.release.wait, 10):
                    raise TimeoutError("文件传输未释放")
            await send(message)

        await self.app(scope, receive, held)


class StorageApiTests(unittest.TestCase):
    def test_actual_first_and_final_body_hold_lease_and_process_lock(self):
        for position in ("first", "last"):
            with self.subTest(position=position), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                settings = Settings(
                    database_url=f"sqlite:///{(root / 'test.db').as_posix()}",
                    data_dir=root / "data", start_background_services=False,
                )
                png = root / "transport.png"
                Image.effect_noise((512, 512), 80).convert("RGB").save(png)
                app = create_app(settings)
                transport = PausedTransport(app, position)
                with TestClient(transport) as client:
                    container = app.state.container
                    with self.assertRaises(RuntimeError):
                        StorageProcessLock(settings.data_dir / "retention/application.lock").acquire()
                    with patch.object(container.screenshots, "evidence_path", return_value=png):
                        with ThreadPoolExecutor(max_workers=1) as pool:
                            future = pool.submit(client.get, "/api/v1/page-evidence/transport/image")
                            try:
                                self.assertTrue(transport.started.wait(10))
                                with container.storage_activity.maintenance() as acquired:
                                    self.assertFalse(acquired)
                            finally:
                                transport.release.set()
                            response = future.result(10)
                    self.assertEqual(200, response.status_code)
                    self.assertEqual(png.read_bytes(), response.content)
                    with container.storage_activity.maintenance() as acquired:
                        self.assertTrue(acquired)
                with StorageProcessLock(settings.data_dir / "retention/application.lock"):
                    pass


if __name__ == "__main__":
    unittest.main()
