import json
import os
import stat
import sys
import tempfile
import time
import unittest
from pathlib import Path

SHARED = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SHARED))

from prepare_single_concurrency_config import (  # noqa: E402
    DIAGNOSTIC_WINDOW_SECONDS,
    SESSION_MAX_AGE_SECONDS,
    prepare_config,
)


class PrepareSingleConcurrencyConfigTests(unittest.TestCase):
    def make_fixture(self, root: Path, candidate: str = "candidate-a") -> tuple[Path, Path, Path]:
        input_path = root / "input-urls.txt"
        input_path.write_text("https://fixture.invalid/article/1\nhttps://fixture.invalid/article/2\n", encoding="utf-8")
        profile = root / "profiles" / candidate
        profile.mkdir(parents=True)
        state = profile / "storage-state.json"
        state.write_text('{"cookies":[],"origins":[]}\n', encoding="utf-8")
        key = candidate.replace("-", "_")
        config = root / "config.json"
        config.write_text(
            json.dumps(
                {
                    "account": "ACCOUNT",
                    "password": "PASSWORD",
                    "input_file": input_path.name,
                    "expected_count": 2000,
                    "window_seconds": 3600,
                    key: {"concurrency": 8, "profile_dir": f"profiles/{candidate}"},
                }
            ),
            encoding="utf-8",
        )
        return config, state, root / "runtime-config.json"

    def test_prepares_single_concurrency_with_fresh_isolated_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, state, target = self.make_fixture(root)
            now = state.stat().st_mtime + 12
            evidence = prepare_config(source=source, target=target, candidate="candidate-a", now_epoch=now)
            generated = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(generated["expected_count"], 2)
            self.assertEqual(generated["window_seconds"], DIAGNOSTIC_WINDOW_SECONDS)
            self.assertEqual(generated["candidate_a"]["concurrency"], 1)
            self.assertEqual(Path(generated["candidate_a"]["profile_dir"]), state.parent.resolve())
            self.assertEqual(evidence["session_age_seconds"], 12)
            if os.name == "posix":
                self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)

    def test_rejects_stale_session_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, state, target = self.make_fixture(root, "candidate-b")
            stale = time.time() - SESSION_MAX_AGE_SECONDS - 1
            os.utime(state, (stale, stale))
            with self.assertRaisesRegex(ValueError, "重新初始化"):
                prepare_config(source=source, target=target, candidate="candidate-b", now_epoch=time.time())
            self.assertFalse(target.exists())

    def test_rejects_missing_session_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, state, target = self.make_fixture(root)
            state.unlink()
            with self.assertRaisesRegex(ValueError, "会话状态缺失"):
                prepare_config(source=source, target=target, candidate="candidate-a")
            self.assertFalse(target.exists())
