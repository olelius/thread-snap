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
        contract = captured["capture_geometry"]
        self.assertEqual("threadsnap.capture-geometry.v1", contract["schema"])
        self.assertEqual("document-css-px", contract["coordinate_space"])
        self.assertEqual(contract["before_sha256"], contract["after_sha256"])
        self.assertRegex(contract["before_sha256"], r"^[0-9a-f]{64}$")
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
        after["media"] = [{"src": "changed", "visible": False}]
        page = FakePage()
        with self.assertRaises(CollectorFailure) as raised:
            capture_bound_screenshot(
                page, FakeCards([before, after, before, after]), "els=>els", page_number=2
            )
        self.assertEqual("PAGE_EVIDENCE_LAYOUT_UNSTABLE", raised.exception.code)
        self.assertEqual(2, page.shots)

    def test_invalid_coordinates_are_rejected_without_clamping(self) -> None:
        for key, value in (("x", -1), ("width", 0), ("height", float("nan")), ("y", 90)):
            with self.subTest(key=key, value=value):
                state = snapshot()
                state["rows"][0]["rect"][key] = value
                page = FakePage()
                with self.assertRaises(CollectorFailure) as raised:
                    capture_bound_screenshot(page, FakeCards([state]), "els=>els", page_number=1)
                self.assertEqual("PAGE_EVIDENCE_LAYOUT_INVALID", raised.exception.code)
                self.assertEqual(0, page.shots)

    def test_pixel_scale_scroll_and_media_must_be_valid(self) -> None:
        states = []
        state = snapshot()
        state["viewport"]["device_scale_factor"] = 2
        states.append((state, "PAGE_EVIDENCE_LAYOUT_INVALID"))
        state = snapshot()
        state["scroll"]["y"] = 10
        states.append((state, "PAGE_EVIDENCE_LAYOUT_INVALID"))
        state = snapshot()
        state["layout_viewport"]["width"] = 105
        states.append((state, "PAGE_EVIDENCE_IMAGE_SIZE_MISMATCH"))
        state = snapshot()
        state["document"]["width"] = 121
        states.append((state, "PAGE_EVIDENCE_IMAGE_SIZE_MISMATCH"))
        state = snapshot()
        state["media"] = [{"visible": True, "src": "image", "complete": False}]
        states.append((state, "PAGE_EVIDENCE_MEDIA_INCOMPLETE"))
        for state, code in states:
            with self.subTest(code=code):
                with self.assertRaises(CollectorFailure) as raised:
                    capture_bound_screenshot(
                        FakePage(), FakeCards([state]), "els=>els", page_number=1
                    )
                self.assertEqual(code, raised.exception.code)

    def test_image_dimensions_and_png_integrity_are_checked(self) -> None:
        for image, code in (
            (png(121, 100), "PAGE_EVIDENCE_IMAGE_SIZE_MISMATCH"),
            (b"not a png", "PAGE_EVIDENCE_IMAGE_INVALID"),
        ):
            with self.subTest(code=code):
                state = snapshot()
                with self.assertRaises(CollectorFailure) as raised:
                    capture_bound_screenshot(
                        FakePage(image), FakeCards([state, state]), "els=>els", page_number=1
                    )
                self.assertEqual(code, raised.exception.code)

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
