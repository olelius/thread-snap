"""确定性抽样的自动化测试。"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SHARED = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SHARED))

from select_inputs import select_urls, write_lf  # noqa: E402


class SelectionTests(unittest.TestCase):
    def test_same_seed_is_reproducible(self) -> None:
        urls = [f"https://TARGET/ugc/article/{index:019d}" for index in range(20)]
        self.assertEqual(select_urls(urls, "seed", 10), select_urls(list(reversed(urls)), "seed", 10))

    def test_lf_output_is_platform_independent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "selected.txt"
            write_lf(path, ["https://TARGET/1", "https://TARGET/2"])
            self.assertEqual(b"https://TARGET/1\nhttps://TARGET/2\n", path.read_bytes())


if __name__ == "__main__":
    unittest.main()
