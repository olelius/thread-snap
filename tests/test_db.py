"""SQLite 连接级并发保护测试。"""

from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path

from sqlalchemy import text

from threadsnap.db import SQLITE_BUSY_TIMEOUT_MILLISECONDS, build_engine


class SQLiteConcurrencyTests(unittest.TestCase):
    def test_sqlite_uses_wal_and_bounded_busy_wait(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            engine = build_engine(f"sqlite:///{Path(directory) / 'test.db'}")
            try:
                with engine.connect() as connection:
                    journal_mode = connection.execute(text("PRAGMA journal_mode")).scalar_one()
                    busy_timeout = connection.execute(text("PRAGMA busy_timeout")).scalar_one()
            finally:
                engine.dispose()

        self.assertEqual("wal", str(journal_mode).casefold())
        self.assertEqual(SQLITE_BUSY_TIMEOUT_MILLISECONDS, busy_timeout)

    def test_second_writer_waits_for_short_transaction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            engine = build_engine(f"sqlite:///{Path(directory) / 'test.db'}")
            with engine.begin() as connection:
                connection.execute(text("CREATE TABLE samples (id INTEGER PRIMARY KEY)"))

            first = engine.connect()
            transaction = first.begin()
            first.execute(text("INSERT INTO samples (id) VALUES (1)"))
            outcome: list[str] = []

            def write_second() -> None:
                with engine.begin() as connection:
                    connection.execute(text("INSERT INTO samples (id) VALUES (2)"))
                outcome.append("written")

            writer = threading.Thread(target=write_second)
            writer.start()
            time.sleep(0.15)
            transaction.commit()
            first.close()
            writer.join(timeout=2)
            try:
                with engine.connect() as connection:
                    count = connection.execute(text("SELECT COUNT(*) FROM samples")).scalar_one()
            finally:
                engine.dispose()

        self.assertEqual(["written"], outcome)
        self.assertEqual(2, count)


if __name__ == "__main__":
    unittest.main()
