"""确定性抽样的自动化测试。"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SHARED = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SHARED))

from select_inputs import select_stratified_urls, select_urls, url_stratum, write_lf  # noqa: E402


class SelectionTests(unittest.TestCase):
    def test_same_seed_is_reproducible(self) -> None:
        urls = [f"https://TARGET/ugc/article/{index:019d}" for index in range(20)]
        self.assertEqual(select_urls(urls, "seed", 10), select_urls(list(reversed(urls)), "seed", 10))

    def test_lf_output_is_platform_independent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "selected.txt"
            write_lf(path, ["https://TARGET/1", "https://TARGET/2"])
            self.assertEqual(b"https://TARGET/1\nhttps://TARGET/2\n", path.read_bytes())

    def test_diagnostic_selection_covers_each_route_and_id_length(self) -> None:
        urls = [
            "https://TARGET/ugc/article/1234567890123456",
            "https://TARGET/ugc/article/1234567890123456789",
            "https://TARGET/article/2234567890123456",
            "https://TARGET/article/2234567890123456789",
        ]
        selected = select_stratified_urls(list(reversed(urls)), "seed")
        self.assertEqual(
            {"article:16", "article:19", "ugc/article:16", "ugc/article:19"},
            {url_stratum(url) for url in selected},
        )


if __name__ == "__main__":
    unittest.main()
