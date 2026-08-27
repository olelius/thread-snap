"""平台中立采集契约与易车已确认入口事实。"""

from __future__ import annotations

import unittest
from contextlib import contextmanager
from pathlib import Path

from threadsnap.collectors import AuthenticationRequired, collector_definition
from threadsnap.collectors.yiche import (
    CollectorFailure,
    YicheCollector,
    is_waf_captcha,
    normalize_post_url,
    parse_circle_url,
    require_content_page,
)

FIXTURES = Path(__file__).parent / "fixtures" / "yiche"


class CollectorRegistryTests(unittest.TestCase):
    def test_dongchedi_definition_keeps_existing_runtime_bounds(self) -> None:
        definition = collector_definition("dongchedi")

        self.assertEqual("懂车帝", definition.display_name)
        self.assertEqual((1, 2000), (definition.min_quantity, definition.max_quantity))
        self.assertEqual((1, 2, 8), (
            definition.min_concurrency,
            definition.default_concurrency,
            definition.max_concurrency,
        ))
        self.assertTrue(definition.default_enabled)

    def test_yiche_definition_is_available_but_starts_disabled_at_conservative_bounds(self) -> None:
        definition = collector_definition("yiche")

        self.assertEqual("易车", definition.display_name)
        self.assertEqual((1, 500), (definition.min_quantity, definition.max_quantity))
        self.assertEqual((1, 1, 1), (
            definition.min_concurrency,
            definition.default_concurrency,
            definition.max_concurrency,
        ))
        self.assertFalse(definition.default_enabled)


class YicheKnownFactsTests(unittest.TestCase):
    def test_circle_orders_and_pages_normalize_to_stable_sources(self) -> None:
        latest_publish = parse_circle_url(
            "https://baa.yiche.com/sample/index-0-1-1.html?tag=-1"
        )
        latest_reply = parse_circle_url("https://baa.yiche.com/sample/index-0-0-2.html")

        self.assertEqual("sample", latest_publish.external_id)
        self.assertEqual("latest_publish", latest_publish.list_order)
        self.assertEqual(
            "https://baa.yiche.com/sample/index-0-1-1.html?tag=-1",
            latest_publish.url,
        )
        self.assertEqual("latest_reply", latest_reply.list_order)
        self.assertEqual("https://baa.yiche.com/sample/index-0-0-1.html", latest_reply.url)

    def test_post_url_strips_query_and_keeps_circle_identity(self) -> None:
        post_id, url = normalize_post_url(
            "https://baa.yiche.com/sample/thread-1001.html?from=community"
        )

        self.assertEqual("1001", post_id)
        self.assertEqual("https://baa.yiche.com/sample/thread-1001.html", url)

    def test_tencent_waf_document_is_control_not_empty_content(self) -> None:
        control = """
        <script src="https://turing.captcha.qcloud.com/TCaptcha.js"></script>
        <script>TencentCaptcha('2017163193'); window.__captcha = true;</script>
        <form action="/WafCaptcha"></form>
        """

        self.assertTrue(is_waf_captcha(control))
        with self.assertRaises(AuthenticationRequired) as caught:
            require_content_page(control, url="https://baa.yiche.com/sample/")
        self.assertEqual("https://baa.yiche.com/sample/", caught.exception.trigger_url)
        self.assertEqual([], caught.exception.records)

    def test_empty_rate_limit_and_signed_api_business_errors_are_distinct(self) -> None:
        with self.assertRaises(CollectorFailure) as empty:
            require_content_page("", url="https://baa.yiche.com/sample/")
        self.assertEqual("EMPTY_RESPONSE", empty.exception.code)

        with self.assertRaises(CollectorFailure) as limited:
            YicheCollector._api_payload(
                [("/web_api/web_forum/api/pc/post/getlist", 429, None)],
                "/post/getlist",
            )
        self.assertEqual("RATE_LIMITED", limited.exception.code)

        with self.assertRaises(CollectorFailure) as unsigned:
            YicheCollector._api_payload(
                [
                    (
                        "/web_api/web_forum/api/pc/post/getlist",
                        200,
                        {"status": "11036", "message": "signature error", "ercd": "11036"},
                    )
                ],
                "/post/getlist",
            )
        self.assertEqual("PLATFORM_RESPONSE_ERROR", unsigned.exception.code)
        self.assertIn("11036", unsigned.exception.message)

    def test_detail_uses_structured_text_and_original_images(self) -> None:
        record = YicheCollector._detail_payload(
            (FIXTURES / "detail.html").read_text(encoding="utf-8"),
            "https://baa.yiche.com/sample/thread-1001.html",
        )

        self.assertEqual("1001", record["platform_post_id"])
        self.assertEqual("结构化正文第一段。\n结构化正文第二段。", record["content"])
        self.assertNotRegex(record["content"], "[\ue000-\uf8ff]")
        self.assertEqual(
            [
                "https://media.example.test/one.jpg",
                "https://media.example.test/two.jpg",
            ],
            record["image_urls"],
        )
        self.assertEqual(1, record["reply_count"])
        self.assertEqual(3, record["like_count"])
        self.assertEqual("unknown", record["visibility"])

    def test_pure_media_detail_is_valid_without_invented_text(self) -> None:
        record = YicheCollector._detail_payload(
            (FIXTURES / "detail-media-only.html").read_text(encoding="utf-8"),
            "https://baa.yiche.com/sample/thread-1002.html",
        )

        self.assertIsNone(record["title"])
        self.assertIsNone(record["content"])
        self.assertEqual(["https://media.example.test/only.jpg"], record["image_urls"])
        self.assertEqual(["https://media.example.test/only.mp4"], record["video_urls"])
        self.assertEqual(
            ["https://media.example.test/only.mp4"],
            YicheCollector(None).resolve_record_video_urls({}, record["video_urls"]),
        )

    def test_private_use_characters_in_structured_text_fail_closed(self) -> None:
        content = (FIXTURES / "detail.html").read_text(encoding="utf-8").replace(
            "结构化正文第一段。", "结构化\ue123正文。"
        )

        with self.assertRaises(CollectorFailure) as caught:
            YicheCollector._detail_payload(
                content, "https://baa.yiche.com/sample/thread-1001.html"
            )
        self.assertEqual("POST_CONTENT_OBFUSCATED", caught.exception.code)

    def test_unverified_comment_continuation_fails_closed(self) -> None:
        import json

        payload = json.loads(
            (FIXTURES / "comments-page-1.json").read_text(encoding="utf-8")
        )
        collector = YicheCollector(None)

        with self.assertRaises(CollectorFailure) as caught:
            collector._parse_comments(
                "<html></html>",
                [("/web_api/information_api/api/v1/comment/top_comment_list", 200, payload)],
                12,
            )
        self.assertEqual("COMMENTS_PAGINATION_UNVERIFIED", caught.exception.code)

    def test_comment_mapping_is_capped_at_ten(self) -> None:
        collector = YicheCollector(None)
        rows = [
            {
                "id": f"c{index}",
                "showName": f"评论者{index}",
                "createTime": "2026-08-27 10:00:00",
                "contentData": {"contentText": f"评论{index}"},
                "likeCount": index,
            }
            for index in range(12)
        ]
        payload = {
            "status": "1",
            "data": {"currentPage": 1, "haveNextPage": True, "list": rows},
        }

        comments = collector._parse_comments(
            "<html></html>",
            [("/web_api/information_api/api/v1/comment/top_comment_list", 200, payload)],
            12,
        )

        self.assertEqual(10, len(comments))
        self.assertEqual("c9", comments[-1]["platform_comment_id"])

    def test_collection_crosses_pages_deduplicates_and_honors_checkpoint(self) -> None:
        collector = YicheCollector(None)
        pages = {
            1: {"list": [{"id": 1001}, {"id": 1001}, {"id": 1002}], "total": 51},
            2: {"list": [{"id": 1003}], "total": 51},
        }
        visited_pages: list[int] = []
        @contextmanager
        def fake_page():
            yield object()

        collector._browser_page = fake_page  # type: ignore[method-assign]
        collector._list_page = lambda _browser, _source, page: (  # type: ignore[method-assign]
            visited_pages.append(page) or pages[page]
        )

        def fake_post(url: str, *, list_row=None) -> dict:
            post_id, normalized = normalize_post_url(url)
            return {
                "platform_post_id": post_id,
                "url": normalized,
                "title": f"样本{post_id}",
                "content": "正文",
                "image_urls": [],
                "video_urls": [],
                "comments": [],
                "visibility": "unknown",
                "raw_status": {},
            }

        collector._fetch_post = lambda _page, url, *, list_row=None: fake_post(  # type: ignore[method-assign]
            url, list_row=list_row
        )
        result = collector.collect_circle(
            "https://baa.yiche.com/sample/index-0-0-1.html",
            2,
            skip_post_ids={"1001"},
        )

        self.assertEqual(["1002", "1003"], [item["platform_post_id"] for item in result["records"]])
        self.assertEqual([1, 2], visited_pages)

    def test_authentication_preserves_completed_checkpoint(self) -> None:
        collector = YicheCollector(None)
        @contextmanager
        def fake_page():
            yield object()

        collector._browser_page = fake_page  # type: ignore[method-assign]
        collector._list_page = lambda *_args: {  # type: ignore[method-assign]
            "list": [{"id": 1001}, {"id": 1002}],
            "total": 2,
        }

        def fake_post(url: str, *, list_row=None) -> dict:
            post_id, normalized = normalize_post_url(url)
            if post_id == "1002":
                raise AuthenticationRequired("需要验证", trigger_url=normalized)
            return {
                "platform_post_id": post_id,
                "url": normalized,
                "content": "正文",
                "image_urls": [],
                "video_urls": [],
                "comments": [],
                "visibility": "unknown",
                "raw_status": {},
            }

        collector._fetch_post = lambda _page, url, *, list_row=None: fake_post(  # type: ignore[method-assign]
            url, list_row=list_row
        )
        with self.assertRaises(AuthenticationRequired) as caught:
            collector.collect_circle("https://baa.yiche.com/sample/", 2)
        self.assertEqual(["1001"], [item["platform_post_id"] for item in caught.exception.records])


if __name__ == "__main__":
    unittest.main()
