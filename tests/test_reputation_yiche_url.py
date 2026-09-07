"""易车临时URL模式的可控响应测试；不访问平台、不启动原生Runtime。"""

import asyncio
import tempfile
import unittest
from pathlib import Path

from threadsnap.reputation_adapter import ReputationAdapterError, ReputationMappingTarget
from threadsnap.reputation_registry import REPUTATION_PLATFORMS
from threadsnap.reputation_yiche import YicheReputationAdapter


class Response:
    status = 200

    def __init__(self, kind, payload):
        self.url = f"https://mapi.yiche.com/point_comment/{kind}?fixture=1"
        self.payload = payload

    async def json(self):
        return self.payload


class Page:
    url = "https://dianping.yiche.com/fixture/koubei/"

    def __init__(self, identity="100", *, empty=False):
        self.identity = identity
        self.empty = empty
        self.handler = None

    def set_default_timeout(self, _value):
        pass

    def on(self, _name, handler):
        self.handler = handler

    async def goto(self, _url, **_kwargs):
        self.handler(
            Response(
                "tags",
                {
                    "data": {
                        "pointCommontInfo": {
                            "serialId": self.identity,
                            "score": "0.00" if self.empty else "4.2",
                            "authorCount": 0 if self.empty else 9,
                        }
                    }
                },
            )
        )
        self.handler(
            Response("query_comment_page_list", {"data": {"total": 0 if self.empty else 12}})
        )
        await asyncio.sleep(0)
        return Response("document", {})

    async def wait_for_selector(self, _selector):
        await asyncio.sleep(0)

    async def wait_for_timeout(self, _ms):
        await asyncio.sleep(0)

    async def add_style_tag(self, **_kwargs):
        pass

    async def evaluate(self, _script):
        return {
            "actual_name": "测试车型",
            "score": None if self.empty else "4.2",
            "rank": "17",
            "rank_scope": "同级车型指数排行",
            "volume": None if self.empty else "9",
            "rect": {"x": 0, "y": 0, "width": 500, "height": 100},
            "document_width": 1440,
            "document_height": 1000,
        }

    async def screenshot(self, **_kwargs):
        raise AssertionError("URL模式不应调用截图")


class Browser:
    def __init__(self, page):
        self.page = page
        self.closed = False

    async def new_context(self, **_kwargs):
        return self

    async def new_page(self):
        return self.page

    async def close(self):
        self.closed = True


class YicheUrlTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.target = ReputationMappingTarget(
            "fixture", "100", Page.url, "测试车型", "fixture-hash"
        )

    async def test_url_metrics_have_no_png_and_no_native_options(self):
        adapter = YicheReputationAdapter(
            None, adb_path="unused", device_serial="unused", headless=False
        )
        self.assertTrue(adapter.headless)
        browser = Browser(Page())
        with tempfile.TemporaryDirectory() as temp:
            result = await adapter._visit(browser, self.target, Path(temp))
            self.assertEqual("4.2", result.score_raw)
            self.assertEqual("12", result.review_article_count_raw)
            self.assertIsNone(result.metric_region_path)
            self.assertIsNone(result.full_page_sha256)
            self.assertEqual([], list(Path(temp).rglob("*.png")))
        self.assertTrue(browser.closed)

    async def test_no_rating_is_empty_but_zero_reviews_are_preserved(self):
        browser = Browser(Page(empty=True))
        with tempfile.TemporaryDirectory() as temp:
            result = await YicheReputationAdapter(None)._visit(browser, self.target, Path(temp))
        self.assertIsNone(result.score_raw)
        self.assertIsNone(result.volume_raw)
        self.assertEqual("0", result.review_article_count_raw)
        self.assertTrue(result.reputation_not_available)

    async def test_identity_failures_are_not_hidden(self):
        browser = Browser(Page(identity="wrong"))
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ReputationAdapterError) as error:
                await YicheReputationAdapter(None)._visit(browser, self.target, Path(temp))
        self.assertEqual("REPUTATION_IDENTITY_MISMATCH", error.exception.code)
        self.assertTrue(browser.closed)

    async def test_valid_score_is_kept_when_author_count_is_missing(self):
        class PartialPage(Page):
            async def goto(self, _url, **_kwargs):
                self.handler(
                    Response(
                        "tags", {"data": {"pointCommontInfo": {"serialId": "100", "score": "4.2"}}}
                    )
                )
                self.handler(Response("query_comment_page_list", {"data": {"total": 0}}))
                await asyncio.sleep(0)
                return Response("document", {})

        with tempfile.TemporaryDirectory() as temp:
            result = await YicheReputationAdapter(None)._visit(
                Browser(PartialPage(empty=True)), self.target, Path(temp)
            )
        self.assertEqual("4.2", result.score_raw)
        self.assertIsNone(result.volume_raw)
        self.assertEqual("0", result.review_article_count_raw)

    async def test_platform_policy_is_scoped_to_yiche(self):
        self.assertFalse(REPUTATION_PLATFORMS["yiche"].requires_evidence)
        self.assertFalse(REPUTATION_PLATFORMS["yiche"].requires_session)
        self.assertIs(REPUTATION_PLATFORMS["yiche"].adapter_factory, YicheReputationAdapter)
        for code in ("dongchedi", "autohome"):
            self.assertTrue(REPUTATION_PLATFORMS[code].requires_evidence)
            self.assertTrue(REPUTATION_PLATFORMS[code].requires_session)
