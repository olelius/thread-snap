"""只覆盖几何绑定与三个平台现有 DOM 读行接口，不访问平台或模型。"""

from __future__ import annotations

import copy
import io
import unittest

from PIL import Image

from threadsnap.collectors.base import CollectorFailure
from threadsnap.collectors.capture_geometry import (
    capture_bound_screenshot,
    capture_browser_launch_args,
)


def snapshot() -> dict:
    """一份同时含页面身份和帖子几何的最小有效快照。"""

    return {
        "rows": [
            {
                "index": 0,
                "href": "https://example.test/thread-1.html",
                "text": "原文",
                "rect": {"x": 10, "y": 20, "width": 80, "height": 30},
            }
        ],
        "document": {"width": 120, "height": 100},
        "viewport": {"width": 120, "height": 100, "device_scale_factor": 1},
        "layout_viewport": {"width": 120, "height": 100},
        "scroll": {"x": 0, "y": 0},
        "url": "https://example.test/list",
        "media": [],
    }


def png(width: int = 120, height: int = 100) -> bytes:
    """生成不依赖任何颜色边界的 PNG 字节。"""

    output = io.BytesIO()
    Image.new("RGB", (width, height), "blue").save(output, format="PNG")
    return output.getvalue()


class FakeCards:
    def __init__(self, snapshots: list[dict]) -> None:
        self.snapshots = copy.deepcopy(snapshots)

    def evaluate_all(self, _script: str) -> dict:
        return self.snapshots.pop(0)


class FakePage:
    def __init__(self, image: bytes | None = None) -> None:
        self.image = image if image is not None else png()
        self.shots = 0
        self.waits: list[int] = []

    def screenshot(self, **kwargs: object) -> bytes:
        assert kwargs == {"full_page": True, "type": "png"}
        self.shots += 1
        return self.image

    def wait_for_timeout(self, timeout: int) -> None:
        self.waits.append(timeout)


class CaptureGeometryTests(unittest.TestCase):
    def test_identical_snapshots_keep_exact_geometry_and_png(self) -> None:
        self.assertIn("--hide-scrollbars", capture_browser_launch_args())
        page = FakePage()
        state = snapshot()
        captured = capture_bound_screenshot(
            page, FakeCards([state, state]), "els=>els", page_number=1
        )
        self.assertEqual(state["rows"], captured["raw_rows"])
        self.assertEqual(page.image, captured["screenshot"])
        self.assertEqual("native-hidden", captured["capture_geometry"]["scrollbar_policy"])
        self.assertEqual(state["document"], captured["capture_geometry"]["png_size"])
        self.assertEqual(1, page.shots)

    def test_any_changed_snapshot_uses_only_one_same_page_retry(self) -> None:
        for field in ("href", "text", "rect", "index"):
            with self.subTest(field=field):
                before = snapshot()
                after = snapshot()
                after["rows"][0][field] = {
                    "href": "https://example.test/thread-2.html",
                    "text": "新文字",
                    "rect": {"x": 10, "y": 22, "width": 80, "height": 30},
                    "index": 1,
                }[field]
                page = FakePage()
                result = capture_bound_screenshot(
                    page, FakeCards([before, after, after, after]), "els=>els", page_number=1
                )
                self.assertEqual(after["rows"], result["raw_rows"])
                self.assertEqual(2, page.shots)
                self.assertEqual([250], page.waits)

    def test_repeated_drift_rejects_png_without_unbounded_retry(self) -> None:
        before, after = snapshot(), snapshot()
        after["rows"][0]["rect"]["y"] += 10
        page = FakePage()
        with self.assertRaises(CollectorFailure) as raised:
            capture_bound_screenshot(
                page, FakeCards([before, after, before, after]), "els=>els", page_number=2
            )
        self.assertEqual("PAGE_EVIDENCE_LAYOUT_UNSTABLE", raised.exception.code)
        self.assertEqual(2, page.shots)

    def test_width_and_png_dimensions_use_existing_retry_codes(self) -> None:
        for key in ("layout_viewport", "document"):
            with self.subTest(key=key):
                state = snapshot()
                state[key]["width"] += 10
                with self.assertRaises(CollectorFailure) as raised:
                    capture_bound_screenshot(
                        FakePage(), FakeCards([state]), "els=>els", page_number=1
                    )
                self.assertEqual("PAGE_EVIDENCE_IMAGE_SIZE_MISMATCH", raised.exception.code)
        state = snapshot()
        with self.assertRaises(CollectorFailure) as raised:
            capture_bound_screenshot(
                FakePage(png(121, 100)), FakeCards([state, state]), "els=>els", page_number=1
            )
        self.assertEqual("PAGE_EVIDENCE_IMAGE_SIZE_MISMATCH", raised.exception.code)

    def test_real_local_dom_readers_share_one_coordinate_contract(self) -> None:
        """三个正式读行脚本在离线HTML中生成真实PNG，不启动采集任务。"""

        from patchright.sync_api import sync_playwright

        from threadsnap.collectors.autohome import CAPTURE_ROWS_SCRIPT as autohome_script
        from threadsnap.collectors.dongchedi import CAPTURE_ROWS_SCRIPT as dongchedi_script
        from threadsnap.collectors.yiche import CAPTURE_ROWS_SCRIPT as yiche_script

        samples = (
            (
                autohome_script,
                "ul.post-list > li",
                '<ul class="post-list"><li>'
                '<p class="post-title"><a href="https://club.autohome.com.cn/bbs/thread/x/1-1.html">'
                "标题</a></p></li></ul>",
            ),
            (
                dongchedi_script,
                "section.community-card",
                '<section class="community-card">'
                '<a href="https://www.dongchedi.com/ugc/article/1">标题</a></section>',
            ),
            (
                yiche_script,
                "a.col-row.bankuai",
                '<div class="col-panel">'
                '<a class="col-row bankuai" href="https://baa.yiche.com/a/ask-1.html">标题</a></div>',
            ),
        )
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, args=capture_browser_launch_args())
            try:
                page = browser.new_page(
                    viewport={"width": 800, "height": 600}, device_scale_factor=1
                )
                for script, selector, content in samples:
                    with self.subTest(selector=selector):
                        page.set_content(content)
                        captured = capture_bound_screenshot(
                            page, page.locator(selector), script, page_number=1
                        )
                        self.assertEqual(1, len(captured["raw_rows"]))
                        self.assertEqual({"width": 800, "height": 600}, captured["document"])
                        self.assertIn("标题", captured["raw_rows"][0]["text"])
            finally:
                browser.close()


if __name__ == "__main__":
    unittest.main()
