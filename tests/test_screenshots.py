"""圈子页面证据、负面框选成果和生命周期专项验证。"""

from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from PIL import Image, ImageChops, ImageDraw
from sqlalchemy import select

from threadsnap.collectors.dongchedi import DongchediCollector
from threadsnap.config import Settings
from threadsnap.db import build_engine, build_session_factory, migrate_database
from threadsnap.models import (
    CirclePageEvidence,
    CircleTask,
    ExtractionRun,
    PostSnapshot,
    ScreenshotArtifactGroup,
    ScreenshotArtifactItem,
    ScreenshotArtifactTile,
    ScreenshotArtifactVersion,
)
from threadsnap.screenshots import ScreenshotService, _recover_card_crop_box


def png_fixture() -> bytes:
    image = Image.new("RGB", (600, 440), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 40, 520, 180), fill="#e2e8f0")
    draw.rectangle((20, 220, 520, 380), fill="#f1f5f9")
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


class CaptureLayoutTests(unittest.TestCase):
    def test_layout_is_measured_only_after_page_top_becomes_stable(self) -> None:
        """顶部栏延迟展开时，应等待新坐标稳定后再进入截图阶段。"""

        events: list[str] = []

        class FakePage:
            def evaluate(self, script: str) -> None:
                self.script = script
                events.append("scroll_top")

            def wait_for_function(self, script: str) -> None:
                self.wait_script = script
                events.append("top_reached")

            def wait_for_timeout(self, timeout: int) -> None:
                events.append(f"wait_{timeout}")

        class FakeCards:
            def __init__(self) -> None:
                self.layouts = [
                    [{"y": 100.0}],
                    [{"y": 130.0}],
                    [{"y": 130.0}],
                    [{"y": 130.0}],
                ]

            def evaluate_all(self, _script: str) -> list[dict[str, float]]:
                events.append("measure")
                return self.layouts.pop(0)

        page = FakePage()
        cards = FakeCards()
        DongchediCollector._stabilize_capture_layout(page, cards, 1)

        self.assertEqual(["scroll_top", "top_reached", "measure"], events[:3])
        self.assertEqual(4, events.count("measure"))
        self.assertEqual(3, events.count("wait_250"))
        self.assertIn("behavior:'instant'", page.script)
        self.assertIn("scrollY === 0", page.wait_script)


class ScreenshotArtifactTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.settings = Settings(
            database_url=f"sqlite:///{(root / 'test.db').as_posix()}",
            data_dir=root / "data",
            start_background_services=False,
        )
        self.settings.ensure_directories()
        migrate_database(self.settings.database_url)
        self.engine = build_engine(self.settings.database_url)
        self.factory = build_session_factory(self.engine)
        self.service = ScreenshotService(self.factory, self.settings)

    def tearDown(self) -> None:
        self.engine.dispose()
        self.temporary.cleanup()

    def create_task(
        self, *, status: str = "running", suffix: str = "1", ai_analysis_enabled: bool = True
    ) -> tuple[str, str]:
        with self.factory.begin() as db:
            run = ExtractionRun(
                number=f"20260823-000000-00{suffix}",
                trigger_type="manual",
                input_mode="circle_discovery",
                status="running",
                idempotency_scope="test",
                idempotency_key=f"run-{suffix}",
                request_hash="a" * 64,
                planned_count=2,
            )
            db.add(run)
            db.flush()
            task = CircleTask(
                run_id=run.id,
                platform_code="dongchedi",
                external_id="24729",
                circle_name="测试圈子",
                circle_url="https://www.dongchedi.com/community/24729",
                section="dynamic",
                list_order="latest_reply",
                status=status,
                queue_sequence=1,
                source_position=0,
                target_count=2,
                config_snapshot={"ai_analysis_enabled": ai_analysis_enabled},
            )
            db.add(task)
            db.flush()
            return run.id, task.id

    def evidence_payload(self) -> dict:
        return {
            "page_number": 1,
            "exact_url": "https://www.dongchedi.com/community/24729",
            "captured_at": "2026-08-23T00:00:00+00:00",
            "adapter_version": "test-v1",
            "browser_version": "test-browser-v1",
            "viewport": {"width": 600, "height": 400},
            "document": {"width": 600, "height": 440},
            "screenshot": png_fixture(),
            "rows": [
                {
                    "post_id": "1001",
                    "url": "https://www.dongchedi.com/ugc/article/1001",
                    "source_position": 0,
                    "text": "负面帖子",
                    "image_count": 1,
                    "rect": {"x": 20, "y": 40, "width": 500, "height": 140},
                },
                {
                    "post_id": "1002",
                    "url": "https://www.dongchedi.com/ugc/article/1002",
                    "source_position": 1,
                    "text": "普通帖子",
                    "image_count": 0,
                    "rect": {"x": 20, "y": 220, "width": 500, "height": 160},
                },
            ],
        }

    def add_posts(self, task_id: str) -> None:
        with self.factory.begin() as db:
            task = db.get(CircleTask, task_id)
            assert task is not None
            for index, (post_id, result) in enumerate(
                (("1001", "negative"), ("1002", "non_negative"))
            ):
                post = PostSnapshot(
                    run_id=task.run_id,
                    circle_task_id=task.id,
                    platform_post_id=post_id,
                    url=f"https://www.dongchedi.com/ugc/article/{post_id}",
                    title=f"帖子 {post_id}",
                    visibility="visible",
                    order_index=index,
                    analysis_status="analysis_completed",
                    sentiment_result=result,
                    sentiment_source="ai",
                    sentiment_updated_at=datetime.now(timezone.utc),
                )
                db.add(post)
                db.flush()
                self.service.link_post(db, task.id, post)
            task.status = "success"
            task.completed_count = 2

    def test_persists_immutable_evidence_and_renders_all_negative_frames(self) -> None:
        run_id, task_id = self.create_task()
        self.service.register_task(task_id)
        self.service.persist_page(task_id, self.evidence_payload())
        loaded = self.service.load_page(task_id, 1)
        self.assertTrue(loaded and loaded["persisted"])
        with self.factory() as db:
            evidence = db.scalar(select(CirclePageEvidence))
            assert evidence is not None
            original_path = Path(evidence.screenshot_path)
        original_bytes = original_path.read_bytes()
        self.add_posts(task_id)
        self.service.mark_task_complete(task_id)
        self.assertTrue(self.service.process_once())

        response = self.service.list_for_run(run_id, "/api/v1")
        group = response["items"][0]
        self.assertEqual((group["status"], group["item_count"], group["negative_count"]), ("ready", 2, 1))
        self.assertEqual(len(group["artifact"]["tiles"]), 1)
        tile_path = self.service.artifact_file(group["id"], 0)
        with Image.open(original_path) as original, Image.open(tile_path) as tile:
            self.assertEqual(tile.size, original.size)
            self.assertEqual(tile.getpixel((22, 42)), (239, 68, 68))
            self.assertEqual(tile.getpixel((10, 10)), original.getpixel((10, 10)))
            self.assertEqual(tile.getpixel((30, 230)), original.getpixel((30, 230)))
            difference = ImageChops.difference(original.convert("RGB"), tile.convert("RGB"))
            self.assertEqual(difference.getbbox(), (22, 42, 519, 179))
        self.assertEqual(original_bytes, original_path.read_bytes())
        package = self.service.artifact_file(group["id"])
        with zipfile.ZipFile(package) as archive:
            self.assertEqual(set(archive.namelist()), {"manifest.json", "tile-0001.png"})
        with self.factory() as db:
            self.assertEqual(len(list(db.scalars(select(ScreenshotArtifactTile)))), 1)
            self.assertEqual(len(list(db.scalars(select(ScreenshotArtifactItem)))), 2)

    def test_sentiment_change_creates_version_and_retains_previous_file(self) -> None:
        _run_id, task_id = self.create_task()
        self.service.register_task(task_id)
        self.service.persist_page(task_id, self.evidence_payload())
        self.add_posts(task_id)
        self.service.mark_task_complete(task_id)
        self.assertTrue(self.service.process_once())
        first_url = self.service.list_for_run(_run_id, "/api/v1")["items"][0]["artifact"][
            "tiles"
        ][0]["image_url"]
        with self.factory.begin() as db:
            post = db.scalar(select(PostSnapshot).where(PostSnapshot.platform_post_id == "1002"))
            assert post is not None
            post.sentiment_result = "negative"
            post.sentiment_source = "manual"
            post.sentiment_updated_at = datetime.now(timezone.utc)
            post_id = post.id
        self.service.mark_all_dirty_for_post(post_id)
        self.assertTrue(self.service.process_once())
        with self.factory() as db:
            group = db.scalar(select(ScreenshotArtifactGroup))
            assert group is not None
            versions = list(
                db.scalars(
                    select(ScreenshotArtifactVersion)
                    .where(ScreenshotArtifactVersion.group_id == group.id)
                    .order_by(ScreenshotArtifactVersion.version)
                )
            )
            self.assertEqual([item.negative_count for item in versions], [1, 2])
            self.assertTrue(all(Path(item.package_path).is_file() for item in versions))
        second_url = self.service.list_for_run(_run_id, "/api/v1")["items"][0]["artifact"][
            "tiles"
        ][0]["image_url"]
        self.assertIn("version=1", first_url)
        self.assertIn("version=2", second_url)
        self.assertNotEqual(first_url, second_url)

    def test_ai_disabled_screenshot_keeps_original_pixels_without_waiting(self) -> None:
        """截图开启且 AI 关闭时直接形成原图成果，不伪造舆情或等待分析。"""

        run_id, task_id = self.create_task(ai_analysis_enabled=False)
        self.service.register_task(task_id)
        self.service.persist_page(task_id, self.evidence_payload())
        with self.factory.begin() as db:
            task = db.get(CircleTask, task_id)
            assert task is not None
            for index, post_id in enumerate(("1001", "1002")):
                post = PostSnapshot(
                    run_id=task.run_id,
                    circle_task_id=task.id,
                    platform_post_id=post_id,
                    url=f"https://www.dongchedi.com/ugc/article/{post_id}",
                    title=f"帖子 {post_id}",
                    visibility="visible",
                    order_index=index,
                    analysis_status="analysis_disabled",
                    sentiment_updated_at=datetime.now(timezone.utc),
                )
                db.add(post)
                db.flush()
                self.service.link_post(db, task.id, post)
            task.status = "success"
            task.completed_count = 2
        self.service.mark_task_complete(task_id)
        self.assertTrue(self.service.process_once())

        group = self.service.list_for_run(run_id, "/api/v1")["items"][0]
        self.assertEqual((group["status"], group["negative_count"]), ("ready", 0))
        with self.factory() as db:
            evidence = db.scalar(select(CirclePageEvidence))
            assert evidence is not None
            original_path = Path(evidence.screenshot_path)
        artifact_path = self.service.artifact_file(group["id"], 0)
        self.assertEqual(original_path.read_bytes(), artifact_path.read_bytes())
        with self.factory() as db:
            sentiments = {
                item.sentiment_result for item in db.scalars(select(ScreenshotArtifactItem))
            }
        self.assertEqual({"not_analyzed"}, sentiments)

    def test_successful_zero_result_generates_empty_artifact_and_failure_is_distinct(self) -> None:
        run_id, task_id = self.create_task(status="success")
        self.service.register_task(task_id)
        self.assertTrue(self.service.process_once())
        result = self.service.list_for_run(run_id, "/api/v1")["items"][0]
        self.assertEqual((result["status"], result["item_count"]), ("empty", 0))

        failed_run_id, failed_task_id = self.create_task(status="failed", suffix="2")
        self.service.register_task(failed_task_id)
        self.assertTrue(self.service.process_once())
        failed = self.service.list_for_run(failed_run_id, "/api/v1")["items"][0]
        self.assertEqual(failed["status"], "failed")

    def test_collector_resume_uses_frozen_manifest_without_recapture(self) -> None:
        collector = DongchediCollector(None, browser_headless=True)
        payload = self.evidence_payload()
        payload["persisted"] = True
        def callback(_payload: dict) -> None:
            self.fail("复用冻结清单时不应再次持久化")

        callback.load = lambda _page: payload  # type: ignore[attr-defined]
        collector.capture_circle_page = lambda *_args: self.fail("复用时不应重新抓取页面")  # type: ignore[method-assign]
        collector.fetch_post = lambda url: {
            "platform_post_id": url.rsplit("/", 1)[-1],
            "url": url,
        }  # type: ignore[method-assign]
        result = collector.collect_circle(
            "https://www.dongchedi.com/community/24729",
            1,
            on_page_evidence=callback,
        )
        self.assertEqual(result["records"][0]["platform_post_id"], "1001")

    def test_supplement_continues_after_a_fully_skipped_frozen_page(self) -> None:
        collector = DongchediCollector(None, browser_headless=True)
        page_one = [
            {
                "post_id": str(index),
                "url": f"https://www.dongchedi.com/ugc/article/{index}",
                "order_index": index - 1,
                "source_position": index - 1,
            }
            for index in range(1, 31)
        ]
        page_two = [
            {
                "post_id": "31",
                "url": "https://www.dongchedi.com/ugc/article/31",
                "order_index": 0,
                "source_position": 30,
            }
        ]

        def callback(_payload: dict) -> None:
            self.fail("冻结清单复用期间不应重复持久化")

        callback.load = lambda page: {  # type: ignore[attr-defined]
            "rows": page_one if page == 1 else page_two if page == 2 else [],
            "persisted": True,
        }
        collector.fetch_post = lambda url: {
            "platform_post_id": url.rsplit("/", 1)[-1],
            "url": url,
        }  # type: ignore[method-assign]
        result = collector.collect_circle(
            "https://www.dongchedi.com/community/24729",
            1,
            skip_post_ids={str(index) for index in range(1, 31)},
            on_page_evidence=callback,
        )
        self.assertEqual([item["platform_post_id"] for item in result["records"]], ["31"])

    def test_renderer_recovers_card_boundaries_from_drifted_evidence_rect(self) -> None:
        """旧证据发生渐进式坐标漂移时，成果裁片仍应覆盖完整可见卡片。"""

        source = Image.new("RGB", (300, 420), "#f7f8fc")
        draw = ImageDraw.Draw(source)
        draw.rectangle((20, 60, 219, 159), fill="white")
        draw.rectangle((20, 180, 229, 319), fill="white")
        first = SimpleNamespace(x=20, y=50, width=190, height=100)
        second = SimpleNamespace(x=20, y=160, width=190, height=140)

        self.assertEqual((20, 60, 220, 160), _recover_card_crop_box(source, first))
        self.assertEqual((20, 180, 230, 320), _recover_card_crop_box(source, second))
        source.close()

    def test_renderer_keeps_each_original_page_as_a_full_size_tile(self) -> None:
        source_paths = [
            Path(self.temporary.name) / "source-one.png",
            Path(self.temporary.name) / "source-two.png",
        ]
        Image.new("RGB", (500, 350), "white").save(source_paths[0])
        Image.new("RGB", (640, 480), "#e2e8f0").save(source_paths[1])
        evidences = [
            SimpleNamespace(
                id=f"evidence-{index}",
                screenshot_path=str(path),
                screenshot_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                run_id=f"run-{index}",
                page_number=index,
                captured_at=datetime(2026, 8, 23, tzinfo=timezone.utc),
            )
            for index, path in enumerate(source_paths, start=1)
        ]
        selected = []
        inputs = []
        for index, evidence in enumerate(evidences):
            item = SimpleNamespace(x=20, y=40, width=200, height=100)
            post = SimpleNamespace(
                id=f"post-{index}",
                platform_post_id=f"platform-{index}",
                title=f"帖子 {index}",
                sentiment_result="negative" if index == 0 else "non_negative",
            )
            selected.append((item, post, evidence))
            inputs.append(
                {
                    "run_number": "20260823-SPLIT-001",
                    "captured_at": "2026-08-23T00:00:00+00:00",
                }
            )
        rendered = self.service._render(  # noqa: SLF001 - 专项验证生产渲染边界。
            {
                "id": "split-height-fixture",
                "circle_name": "分片测试圈子",
                "external_id": "fixture",
                "list_order": "latest_reply",
            },
            1,
            selected,
            inputs,
        )
        self.assertEqual([(tile["width"], tile["height"]) for tile in rendered["tiles"]], [(500, 350), (640, 480)])
        self.assertEqual(len(rendered["items"]), 2)
        self.assertEqual(
            sum(1 for item in rendered["items"] if item["sentiment_result"] == "negative"),
            1,
        )
        first_item = rendered["items"][0]
        self.assertEqual(100, first_item["height"])
        self.assertEqual(40, first_item["y"])
        self.assertEqual("20260823-SPLIT-001", first_item["run_number"])
        self.assertEqual("2026-08-23T00:00:00+00:00", first_item["captured_at"])
        with Image.open(rendered["tiles"][0]["path"]) as tile:
            self.assertEqual((500, 350), tile.size)
            self.assertEqual((255, 255, 255), tile.getpixel((10, 10)))
            self.assertEqual((239, 68, 68), tile.getpixel((22, 42)))
        with Image.open(rendered["tiles"][1]["path"]) as tile:
            self.assertEqual((640, 480), tile.size)
            self.assertEqual((226, 232, 240), tile.getpixel((22, 42)))
        with zipfile.ZipFile(rendered["package_path"]) as archive:
            manifest = json.loads(archive.read("manifest.json"))
        self.assertEqual("threadsnap.screenshot-artifact.v2", manifest["schema"])
        self.assertEqual("v4-full-page-evidence-background", manifest["renderer_version"])


if __name__ == "__main__":
    unittest.main()
