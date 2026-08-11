import sys
import tempfile
import unittest
from pathlib import Path

SHARED = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SHARED))

from session_profile import prepare_isolated_profile, promote_isolated_profile  # noqa: E402


class SessionProfileTests(unittest.TestCase):
    def test_prepare_does_not_touch_existing_target_profile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "profiles" / "candidate-a"
            target.mkdir(parents=True)
            (target / "storage-state.json").write_text("old", encoding="utf-8")
            source = prepare_isolated_profile(root / "runtime" / "browser-profile")
            (source / "storage-state.json").write_text("new", encoding="utf-8")
            self.assertEqual("old", (target / "storage-state.json").read_text(encoding="utf-8"))

    def test_promote_replaces_target_only_after_new_state_exists(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "profiles" / "candidate-a"
            target.mkdir(parents=True)
            (target / "storage-state.json").write_text("old", encoding="utf-8")
            source = prepare_isolated_profile(root / "runtime" / "browser-profile")
            (source / "storage-state.json").write_text("new", encoding="utf-8")
            backup = root / "runtime" / "previous-profile"
            promote_isolated_profile(source, target, backup)
            self.assertEqual("new", (target / "storage-state.json").read_text(encoding="utf-8"))
            self.assertFalse(source.exists())
            self.assertFalse(backup.exists())

    def test_promote_rejects_incomplete_new_profile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = prepare_isolated_profile(root / "runtime" / "browser-profile")
            target = root / "profiles" / "candidate-a"
            target.mkdir(parents=True)
            (target / "storage-state.json").write_text("old", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "storage-state"):
                promote_isolated_profile(source, target, root / "runtime" / "previous-profile")
            self.assertEqual("old", (target / "storage-state.json").read_text(encoding="utf-8"))
