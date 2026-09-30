"""验证清理互斥覆盖业务执行和文件响应的完整生命周期。"""

import asyncio
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from threadsnap.storage_activity import (
    StorageActivity,
    StorageActivityMiddleware,
    storage_operation,
)


class StorageActivityTests(unittest.TestCase):
    def test_parallel_leases_and_cross_thread_idempotent_release(self):
        gate = StorageActivity()
        first, second = gate.try_acquire(), gate.try_acquire()
        with gate.maintenance() as acquired:
            self.assertFalse(acquired)
        thread = threading.Thread(target=first.release)
        thread.start()
        thread.join()
        first.release()
        with gate.maintenance() as acquired:
            self.assertFalse(acquired)
        second.release()
        with gate.maintenance() as acquired:
            self.assertTrue(acquired)
            self.assertIsNone(gate.try_acquire())

    def test_background_exception_releases_lease_and_busy_skips(self):
        gate = StorageActivity()

        class Background:
            storage_activity = gate

            @storage_operation(False)
            def process_once(self):
                raise ValueError("测试业务异常")

        worker = Background()
        with self.assertRaises(ValueError):
            worker.process_once()
        with gate.maintenance() as acquired:
            self.assertTrue(acquired)
            self.assertFalse(worker.process_once())

    def test_response_lease_lasts_through_last_body_and_disconnect(self):
        async def scenario(disconnected):
            gate = StorageActivity()
            sent_header, finish_body = asyncio.Event(), asyncio.Event()

            async def app(scope, receive, send):
                await send({"type": "http.response.start", "status": 200, "headers": []})
                sent_header.set()
                await finish_body.wait()
                if disconnected:
                    raise ConnectionError("客户端断开")
                await send({"type": "http.response.body", "body": b"png", "more_body": False})

            async def send(message):
                pass

            async def receive():
                return {"type": "http.request", "body": b""}

            scope = {
                "type": "http", "method": "GET", "path": "/api/v1/page-evidence/x/image",
                "app": SimpleNamespace(state=SimpleNamespace(
                    container=SimpleNamespace(storage_activity=gate)
                )),
            }
            task = asyncio.create_task(StorageActivityMiddleware(app)(scope, receive, send))
            await sent_header.wait()
            with gate.maintenance() as acquired:
                self.assertFalse(acquired, "路由返回/响应头发送后仍须保护文件正文")
            finish_body.set()
            if disconnected:
                with self.assertRaises(ConnectionError):
                    await task
            else:
                await task
            with gate.maintenance() as acquired:
                self.assertTrue(acquired)

        asyncio.run(scenario(False))
        asyncio.run(scenario(True))

    def test_sse_does_not_permanently_block_cleanup(self):
        async def app(scope, receive, send):
            with gate.maintenance() as acquired:
                self.assertTrue(acquired)

        gate = StorageActivity()
        scope = {"type": "http", "method": "GET", "path": "/api/v1/events"}
        asyncio.run(StorageActivityMiddleware(app)(scope, None, None))

    def test_manual_delete_is_exclusive_and_busy_is_retryable(self):
        async def scenario(busy):
            gate = StorageActivity()
            lease = gate.try_acquire() if busy else None
            messages = []

            async def app(scope, receive, send):
                self.assertIsNone(gate.try_acquire(), "删除期间不允许新文件读写")

            async def send(message):
                messages.append(message)

            async def no_delay(_seconds):
                pass

            scope = {
                "type": "http", "method": "DELETE", "path": "/api/v1/runs/x",
                "app": SimpleNamespace(state=SimpleNamespace(
                    container=SimpleNamespace(storage_activity=gate)
                )),
            }
            with patch("threadsnap.storage_activity.asyncio.sleep", no_delay):
                await StorageActivityMiddleware(app)(scope, None, send)
            if busy:
                self.assertEqual(503, messages[0]["status"])
                self.assertIn(b"STORAGE_BUSY", messages[1]["body"])
                lease.release()
            with gate.maintenance() as acquired:
                self.assertTrue(acquired)

        asyncio.run(scenario(False))
        asyncio.run(scenario(True))


if __name__ == "__main__":
    unittest.main()
