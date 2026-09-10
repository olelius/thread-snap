"""易车临时URL模式的可控响应测试；不访问平台、不启动原生Runtime。"""

import asyncio
import tempfile
import unittest
from pathlib import Path

from threadsnap.reputation import ReputationService
from threadsnap.reputation_adapter import ReputationAdapterError, ReputationMappingTarget
from threadsnap.reputation_registry import REPUTATION_PLATFORMS, metric_label
from threadsnap.reputation_yiche import (
    YicheReputationAdapter,
    parse_mobile_rank,
    parse_owner_review_count,
)


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
        self.request = self

    async def new_context(self, **_kwargs):
        return self

    async def new_page(self):
        return self.page

    async def get(self, url):
        if "serial_rating_sort" in url:
            payload = {
                "status": "1",
                "data": {
                    "serialList": []
                    if self.page.empty
                    else [
                        {"serialId": 100, "serialName": "测试车型", "rating": "4.2"},
                        {"serialId": 200, "serialName": "其它车型", "rating": "4.1"},
                    ]
                },
            }
        else:
            payload = {
                "status": "1",
                "data": {
                    "ratingCard": {
                        "serialId": 100,
                        "topicCount": 0 if self.page.empty else 7,
                        "authorCount": 0 if self.page.empty else 9,
                    }
                },
            }
        return Response("mobile", payload)

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
            self.assertEqual("1", result.rank_raw)
            self.assertEqual("9", result.volume_raw)
            self.assertEqual("7", result.owner_review_count_raw)
            self.assertIsNone(result.review_article_count_raw)
            metrics = ReputationService._official_metrics(result, None, "yiche")
            self.assertEqual("9", metrics["volume"]["raw"])
            self.assertEqual("7", metrics["owner_review_count"]["raw"])
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
        self.assertEqual("0", result.owner_review_count_raw)
        self.assertIsNone(result.review_article_count_raw)
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
        self.assertIsNone(result.review_article_count_raw)

    def test_mobile_metric_contracts_keep_rank_and_counts_separate(self):
        rank, scope, rows = parse_mobile_rank(
            {
                "status": "1",
                "data": {
                    "serialList": [
                        {"serialId": 200, "rating": "4.3"},
                        {"serialId": 100, "rating": "4.2"},
                    ]
                },
            },
            "100",
        )
        self.assertEqual("2", rank)
        self.assertIn(":100:", scope)
        self.assertEqual(2, len(rows))
        owner, participants = parse_owner_review_count(
            {
                "status": "1",
                "data": {
                    "ratingCard": {
                        "serialId": 100,
                        "topicCount": 1086,
                        "authorCount": 1396,
                    }
                },
            },
            "100",
        )
        self.assertEqual("1086", owner)
        self.assertEqual("1396", participants)

    async def test_platform_policy_is_scoped_to_yiche(self):
        self.assertFalse(REPUTATION_PLATFORMS["yiche"].requires_evidence)
        self.assertFalse(REPUTATION_PLATFORMS["yiche"].requires_session)
        self.assertIs(REPUTATION_PLATFORMS["yiche"].adapter_factory, YicheReputationAdapter)
        self.assertEqual(
            ("score", "rank", "volume", "owner_review_count"),
            REPUTATION_PLATFORMS["yiche"].metric_keys,
        )
        self.assertEqual("参与人数", metric_label("yiche", "volume"))
        self.assertEqual("车主点评", metric_label("yiche", "owner_review_count"))
        for code in ("dongchedi", "autohome"):
            self.assertTrue(REPUTATION_PLATFORMS[code].requires_evidence)
            self.assertTrue(REPUTATION_PLATFORMS[code].requires_session)
