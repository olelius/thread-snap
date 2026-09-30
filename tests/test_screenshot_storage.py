"""截图物理复用、不可变版本下载和懒 ZIP 的真实 SQLite/磁盘验证。"""

from __future__ import annotations

import errno
import hashlib
import io
import json
import os
import threading
import unittest
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw
from sqlalchemy import select

from tests import test_screenshots as screenshot_fixtures
from threadsnap.errors import DomainError
from threadsnap.models import (
    CirclePageEvidence,
    PostSnapshot,
    ScreenshotArtifactTile,
    ScreenshotArtifactVersion,
)

png_fixture = screenshot_fixtures.png_fixture


class ScreenshotStorageTests(unittest.TestCase):
    """复用现有建库夹具，不继承测试用例，避免机械重复整套截图验证。"""

    setUp = screenshot_fixtures.ScreenshotArtifactTests.setUp
    tearDown = screenshot_fixtures.ScreenshotArtifactTests.tearDown
    create_task = screenshot_fixtures.ScreenshotArtifactTests.create_task
    evidence_payload = screenshot_fixtures.ScreenshotArtifactTests.evidence_payload
    add_posts = screenshot_fixtures.ScreenshotArtifactTests.add_posts

    def render(self, *, negative: bool = False, suffix: str = "1") -> tuple[str, Path, Path, Path]:
        """通过正式页面持久化和成果队列生成单页两卡成果。"""

        run_id, task_id = self.create_task(suffix=suffix)
        self.service.persist_page(task_id, self.evidence_payload())
        self.add_posts(task_id)
        if not negative:
            with self.factory.begin() as db:
                for post in db.scalars(select(PostSnapshot)):
                    post.sentiment_result = "non_negative"
        self.service.mark_task_complete(task_id)
        self.assertTrue(self.service.process_once())
        group = self.service.list_for_run(run_id, "/api/v1")["items"][0]
        with self.factory() as db:
            evidence = db.scalar(
                select(CirclePageEvidence).where(CirclePageEvidence.circle_task_id == task_id)
            )
            version = db.scalar(
                select(ScreenshotArtifactVersion).where(ScreenshotArtifactVersion.group_id == group["id"])
            )
            return (
                group["id"],
                Path(evidence.screenshot_path),
                Path(version.tiles[0]["path"]),
                Path(version.package_path),
            )

    @staticmethod
    def separate_copy(path: Path) -> None:
        """把新硬链接还原成独立文件，以代表优化前的存量副本。"""

        content = path.read_bytes()
        path.unlink()
        path.write_bytes(content)

    def test_unboxed_png_is_linked_and_survives_either_path_deleted(self) -> None:
        group_id, original, tile, _package = self.render()
        self.assertNotEqual(original, tile)
        self.assertTrue(original.samefile(tile))
        self.assertEqual(png_fixture(), tile.read_bytes())
        tile.unlink()
        self.assertEqual(png_fixture(), original.read_bytes())
        os.link(original, tile)
        original.unlink()
        self.assertEqual(png_fixture(), self.service.artifact_file(group_id, 0).read_bytes())
        with zipfile.ZipFile(self.service.artifact_file(group_id)) as archive:
            self.assertEqual(png_fixture(), archive.read("tile-0001.png"))

    def test_cross_device_link_falls_back_to_unchanged_png_copy(self) -> None:
        with patch("threadsnap.screenshots.os.link", side_effect=OSError(errno.EXDEV, "cross device")):
            _group_id, original, tile, _package = self.render()
        self.assertFalse(original.samefile(tile))
        self.assertEqual(original.read_bytes(), tile.read_bytes())
        original.unlink()
        self.assertEqual(png_fixture(), tile.read_bytes())

    def test_negative_png_matches_previous_renderer_every_pixel(self) -> None:
        _group_id, original, tile, _package = self.render(negative=True)
        with Image.open(io.BytesIO(png_fixture())) as frozen:
            expected = frozen.convert("RGB")
        ImageDraw.Draw(expected).rectangle((22, 42, 517, 177), outline="#ef4444", width=5)
        with Image.open(tile) as actual:
            self.assertEqual(expected.size, actual.size)
            self.assertEqual(expected.tobytes(), actual.convert("RGB").tobytes())
        self.assertFalse(original.samefile(tile))
        self.assertEqual(png_fixture(), original.read_bytes())

    def test_zip_created_once_from_frozen_input_under_concurrent_downloads(self) -> None:
        group_id, _original, tile, package = self.render(negative=True)
        manifest_path = package.parent / "manifest.json"
        manifest_bytes = manifest_path.read_bytes()
        self.assertFalse(package.exists())
        with self.factory() as db:
            self.assertEqual("", db.scalar(select(ScreenshotArtifactVersion)).package_sha256)
        barrier = threading.Barrier(5)

        def download() -> Path:
            barrier.wait(timeout=5)
            return self.service.artifact_file(group_id, version=1)

        with patch("threadsnap.screenshots.zipfile.ZipFile", wraps=zipfile.ZipFile) as build:
            with ThreadPoolExecutor(max_workers=5) as executor:
                files = list(executor.map(lambda _: download(), range(5)))
            self.assertEqual(1, build.call_count)
        self.assertEqual([package] * 5, files)
        with zipfile.ZipFile(package) as archive:
            self.assertEqual({"manifest.json", "tile-0001.png"}, set(archive.namelist()))
            self.assertTrue(all(item.compress_type == zipfile.ZIP_STORED for item in archive.infolist()))
            self.assertEqual(manifest_bytes, archive.read("manifest.json"))
            self.assertEqual(tile.read_bytes(), archive.read("tile-0001.png"))
        with self.factory() as db:
            version = db.scalar(select(ScreenshotArtifactVersion))
            self.assertEqual(hashlib.sha256(package.read_bytes()).hexdigest(), version.package_sha256)
        self.assertEqual(manifest_bytes, manifest_path.read_bytes())

    def test_existing_historical_zip_is_returned_without_rewriting(self) -> None:
        group_id, original, _tile, package = self.render()
        with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("old-frozen-member.png", original.read_bytes())
        old = package.read_bytes()
        with self.factory.begin() as db:
            db.scalar(select(ScreenshotArtifactVersion)).package_sha256 = hashlib.sha256(old).hexdigest()
        with patch("threadsnap.screenshots.zipfile.ZipFile", side_effect=AssertionError("must reuse")):
            self.assertEqual(package, self.service.artifact_file(group_id))
        self.assertEqual(old, package.read_bytes())

    def test_historical_tile_and_zip_select_frozen_version_not_current(self) -> None:
        group_id, original, first_tile, first_package = self.render()
        first_sha = hashlib.sha256(first_tile.read_bytes()).hexdigest()
        with self.factory.begin() as db:
            post = db.scalar(select(PostSnapshot).where(PostSnapshot.platform_post_id == "1001"))
            post.sentiment_result = "negative"
            post_id = post.id
        self.service.mark_all_dirty_for_post(post_id)
        self.assertTrue(self.service.process_once())
        current_tile = self.service.artifact_file(group_id, 0)
        self.assertNotEqual(first_tile, current_tile)
        self.assertEqual(first_tile, self.service.artifact_file(group_id, 0, version=1, sha256=first_sha))
        self.assertEqual(png_fixture(), first_tile.read_bytes())
        self.assertEqual(png_fixture(), original.read_bytes())
        self.assertNotEqual(current_tile.read_bytes(), first_tile.read_bytes())
        self.assertEqual(first_package, self.service.artifact_file(group_id, version=1))
        with zipfile.ZipFile(first_package) as archive:
            self.assertEqual(png_fixture(), archive.read("tile-0001.png"))
        with self.assertRaises(DomainError) as error:
            self.service.artifact_file(group_id, 0, version=2, sha256=first_sha)
        self.assertEqual("ARTIFACT_HASH_MISMATCH", error.exception.code)
        with self.assertRaises(DomainError):
            self.service.artifact_file(group_id, 0, version=999)

    def test_corrupt_png_prevents_publish_and_retry_uses_frozen_file(self) -> None:
        group_id, _original, tile, package = self.render(negative=True)
        original_tile = tile.read_bytes()
        tile.write_bytes(b"corrupt")
        with self.assertRaises(DomainError) as error:
            self.service.artifact_file(group_id)
        self.assertEqual("ARTIFACT_PACKAGE_FAILED", error.exception.code)
        self.assertFalse(package.exists())
        self.assertEqual([], list(package.parent.glob("*.tmp")))
        tile.write_bytes(original_tile)
        self.assertEqual(package, self.service.artifact_file(group_id))

    def test_publication_failure_leaves_no_partial_zip(self) -> None:
        group_id, _original, tile, package = self.render()
        with patch("threadsnap.screenshots.os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(DomainError):
                self.service.artifact_file(group_id)
        self.assertFalse(package.exists())
        self.assertEqual([], list(package.parent.glob("*.tmp")))
        self.assertEqual(png_fixture(), tile.read_bytes())
        self.assertEqual(package, self.service.artifact_file(group_id))

    def test_manifest_mismatch_and_outside_version_paths_are_rejected(self) -> None:
        group_id, _original, tile, package = self.render()
        manifest_path = package.parent / "manifest.json"
        frozen = manifest_path.read_bytes()
        manifest = json.loads(frozen)
        manifest["version"] = 2
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaises(DomainError):
            self.service.artifact_file(group_id)
        self.assertFalse(package.exists())
        manifest_path.write_bytes(frozen)
        with self.factory.begin() as db:
            row = db.scalar(select(ScreenshotArtifactVersion))
            row.tiles = [{**row.tiles[0], "path": str(tile.parent.parent / tile.name)}]
        with self.assertRaises(DomainError) as error:
            self.service.artifact_file(group_id, 0)
        self.assertEqual("ARTIFACT_PATH_INVALID", error.exception.code)
        self.assertEqual(png_fixture(), tile.read_bytes())

    def test_missing_old_deflated_zip_does_not_replace_historical_bytes(self) -> None:
        group_id, _original, tile, package = self.render()
        with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(tile, "tile-0001.png")
        old_hash = hashlib.sha256(package.read_bytes()).hexdigest()
        with self.factory.begin() as db:
            db.scalar(select(ScreenshotArtifactVersion)).package_sha256 = old_hash
        package.unlink()
        with self.assertRaises(DomainError) as error:
            self.service.artifact_file(group_id)
        self.assertEqual("ARTIFACT_PACKAGE_MISMATCH", error.exception.code)
        self.assertFalse(package.exists())
        with self.factory() as db:
            self.assertEqual(old_hash, db.scalar(select(ScreenshotArtifactVersion)).package_sha256)

    def test_missing_new_zip_recreates_identical_bytes_despite_mtime_change(self) -> None:
        group_id, _original, tile, package = self.render()
        self.service.artifact_file(group_id)
        first_bytes = package.read_bytes()
        package.unlink()
        os.utime(tile, (1000000000, 1000000000))
        self.service.artifact_file(group_id)
        self.assertEqual(first_bytes, package.read_bytes())

    def test_atomic_publish_hash_registration_can_resume_after_failure(self) -> None:
        group_id, _original, _tile, package = self.render()
        with patch.object(self.service, "_record_package_hash", side_effect=OSError("db unavailable")):
            with self.assertRaises(DomainError):
                self.service.artifact_file(group_id)
        frozen = package.read_bytes()
        self.assertEqual(package, self.service.artifact_file(group_id))
        self.assertEqual(frozen, package.read_bytes())
        with self.factory() as db:
            self.assertEqual(
                hashlib.sha256(frozen).hexdigest(),
                db.scalar(select(ScreenshotArtifactVersion)).package_sha256,
            )

    def test_existing_copies_compact_atomically_and_repeat_is_noop(self) -> None:
        group_id, original, tile, package = self.render()
        self.separate_copy(tile)
        self.service.artifact_file(group_id)
        package_bytes = package.read_bytes()
        self.assertFalse(original.samefile(tile))
        result = self.service.compact_identical_pngs()
        self.assertEqual(2, result["registered_files"])
        self.assertEqual(1, result["linked_files"])
        self.assertEqual(len(png_fixture()), result["linked_logical_bytes"])
        self.assertTrue(original.samefile(tile))
        self.assertEqual(package_bytes, package.read_bytes())
        second = self.service.compact_identical_pngs()
        self.assertEqual(0, second["linked_files"])
        self.assertEqual(1, second["already_linked_files"])
        original.unlink()
        self.assertEqual(png_fixture(), tile.read_bytes())

    def test_compaction_skips_hash_mismatch_unregistered_and_outside_paths(self) -> None:
        _group_id, original, tile, _package = self.render()
        self.separate_copy(tile)
        tile.write_bytes(b"damaged registered PNG")
        unregistered = original.parent / "not-registered.png"
        unregistered.write_bytes(png_fixture())
        outside = self.settings.data_dir.parent / "outside.png"
        outside.write_bytes(png_fixture())
        with self.factory.begin() as db:
            row = db.scalar(select(ScreenshotArtifactTile))
            row.file_path = str(outside)
        result = self.service.compact_identical_pngs()
        self.assertEqual(3, result["registered_files"])
        self.assertEqual(0, result["linked_files"])
        self.assertEqual(2, result["skipped_files"])
        self.assertEqual(b"damaged registered PNG", tile.read_bytes())
        self.assertFalse(original.samefile(unregistered))
        self.assertFalse(original.samefile(outside))

    def test_compaction_link_failure_preserves_both_files(self) -> None:
        _group_id, original, tile, _package = self.render()
        self.separate_copy(tile)
        with patch("threadsnap.screenshots.os.link", side_effect=OSError(errno.EPERM, "not supported")):
            result = self.service.compact_identical_pngs()
        self.assertEqual(1, result["failed_files"])
        self.assertEqual(0, result["linked_files"])
        self.assertFalse(original.samefile(tile))
        self.assertEqual(png_fixture(), tile.read_bytes())
        self.assertEqual([], list(tile.parent.glob("*.link")))

    def test_compaction_across_batches_preserves_surviving_batch_paths(self) -> None:
        first_group, first_original, first_tile, _first_zip = self.render(suffix="1")
        second_group, second_original, second_tile, second_zip = self.render(suffix="2")
        self.assertNotEqual(first_group, second_group)
        self.assertFalse(first_original.samefile(second_original))
        result = self.service.compact_identical_pngs()
        self.assertEqual(4, result["registered_files"])
        self.assertEqual(2, result["linked_files"])
        self.assertTrue(first_original.samefile(second_original))
        self.assertTrue(first_tile.samefile(second_tile))
        first_original.unlink()
        first_tile.unlink()
        self.assertEqual(png_fixture(), second_original.read_bytes())
        self.assertEqual(png_fixture(), self.service.artifact_file(second_group, 0).read_bytes())
        self.assertEqual(second_zip, self.service.artifact_file(second_group))

    def test_compaction_replace_failure_does_not_unlink_original_target(self) -> None:
        _group_id, original, tile, _package = self.render()
        self.separate_copy(tile)
        with patch("threadsnap.screenshots.os.replace", side_effect=OSError("rename failed")):
            result = self.service.compact_identical_pngs()
        self.assertEqual(1, result["failed_files"])
        self.assertEqual(0, result["linked_files"])
        self.assertFalse(original.samefile(tile))
        self.assertEqual(png_fixture(), original.read_bytes())
        self.assertEqual(png_fixture(), tile.read_bytes())
        self.assertEqual([], list(tile.parent.glob("*.link")))


if __name__ == "__main__":
    unittest.main()
