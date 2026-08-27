"""平台中立采集契约与易车已确认入口事实。"""

from __future__ import annotations

import unittest
from contextlib import contextmanager
from datetime import timezone
from pathlib import Path

from threadsnap.collectors import AuthenticationRequired, get_platform_spec
from threadsnap.collectors.yiche import (
    ApiEvent,
    CollectorFailure,
    YicheCollector,
    _parse_time,
    _request_content_id,
    is_waf_captcha,
    normalize_post_url,
    parse_circle_url,
    require_content_page,
)

FIXTURES = Path(__file__).parent / "fixtures" / "yiche"


def api_event(
    path: str,
    payload: object,
    *,
    content_id: str | None = None,
    status: int = 200,
) -> ApiEvent:
    """构造不含动态请求参数的脱敏页面业务事件。"""

    return ApiEvent(path, status, payload, content_id)


class CollectorRegistryTests(unittest.TestCase):
    def test_dongchedi_definition_keeps_existing_runtime_bounds(self) -> None:
        definition = get_platform_spec("dongchedi")

        self.assertEqual("懂车帝", definition.display_name)
        self.assertEqual((1, 2000), (definition.min_quantity, definition.max_quantity))
        self.assertEqual((1, 2, 8), (
            definition.min_concurrency,
            definition.default_concurrency,
            definition.max_concurrency,
        ))
        self.assertTrue(definition.default_enabled)
        self.assertEqual("available", definition.adapter_status)
        self.assertTrue(definition.supports_page_evidence)

    def test_yiche_definition_is_unreleased_at_conservative_bounds(self) -> None:
        definition = get_platform_spec("yiche")

        self.assertEqual("易车", definition.display_name)
        self.assertEqual((1, 500), (definition.min_quantity, definition.max_quantity))
        self.assertEqual((1, 1, 1), (
            definition.min_concurrency,
            definition.default_concurrency,
            definition.max_concurrency,
        ))
        self.assertFalse(definition.default_enabled)
        self.assertEqual("not_integrated", definition.adapter_status)
        self.assertFalse(definition.supports_page_evidence)


class YicheKnownFactsTests(unittest.TestCase):
    def test_comment_request_keeps_only_content_identity(self) -> None:
        self.assertEqual(
            "1001",
            _request_content_id(
                "https://api.example.test/comment?param=%7B%22contentId%22%3A1001%2C%22pageSize%22%3A20%7D"
            ),
        )

    def test_naive_platform_time_is_attached_to_asia_shanghai(self) -> None:
        parsed = _parse_time("2026-08-27 10:20:30")
        assert parsed is not None
        self.assertEqual(8 * 3600, int(parsed.utcoffset().total_seconds()))
        self.assertEqual(2, parsed.astimezone(timezone.utc).hour)

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
                [api_event("/web_api/web_forum/api/pc/post/getlist", None, status=429)],
                "/post/getlist",
            )
        self.assertEqual("RATE_LIMITED", limited.exception.code)

        with self.assertRaises(CollectorFailure) as unsigned:
            YicheCollector._api_payload(
                [api_event(
                    "/web_api/web_forum/api/pc/post/getlist",
                    {"status": "11036", "message": "signature error", "ercd": "11036"},
                )],
                "/post/getlist",
            )
        self.assertEqual("YICHE_PUBLIC_PARAMS_MISSING", unsigned.exception.code)
        self.assertIn("11036", unsigned.exception.message)

        with self.assertRaises(CollectorFailure) as missing_identity:
            YicheCollector._api_payload(
                [api_event(
                    "/web_api/information_api/api/v1/comment/top_comment_list",
                    {"status": "400", "message": "content id missing"},
                )],
                "/comment/top_comment_list",
                expected_content_id="1001",
            )
        self.assertEqual("YICHE_COMMENT_IDENTITY_MISSING", missing_identity.exception.code)
        self.assertIn("400", missing_identity.exception.message)

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
        assert record["published_at"] is not None
        self.assertEqual(8 * 3600, int(record["published_at"].utcoffset().total_seconds()))
        self.assertEqual(2, record["published_at"].astimezone(timezone.utc).hour)

    def test_detail_rejects_matching_post_id_from_wrong_circle(self) -> None:
        with self.assertRaises(CollectorFailure) as caught:
            YicheCollector._detail_payload(
                (FIXTURES / "detail.html").read_text(encoding="utf-8"),
                "https://baa.yiche.com/wrong-circle/thread-1001.html",
            )
        self.assertEqual("POST_IDENTITY_MISMATCH", caught.exception.code)

    def test_url_collection_rejects_wrong_circle_even_when_post_id_matches(self) -> None:
        collector = YicheCollector(None)
        content = (FIXTURES / "detail.html").read_text(encoding="utf-8")
        collector._navigate = lambda _page, url: (content, [], url)  # type: ignore[method-assign]

        with self.assertRaises(CollectorFailure) as caught:
            collector._fetch_post(
                object(), "https://baa.yiche.com/wrong-circle/thread-1001.html"
            )
        self.assertEqual("POST_IDENTITY_MISMATCH", caught.exception.code)

    def test_successful_document_identity_and_comment_proof_mark_visible(self) -> None:
        collector = YicheCollector(None)
        content = (FIXTURES / "detail.html").read_text(encoding="utf-8")
        event = api_event(
            "/web_api/information_api/api/v1/comment/top_comment_list",
            {
                "status": "1",
                "data": {
                    "currentPage": 1,
                    "pageSize": 20,
                    "total": 1,
                    "haveNextPage": False,
                    "list": [{"id": "c1", "contentData": {"contentText": "一级评论"}}],
                },
            },
            content_id="1001",
        )
        url = "https://baa.yiche.com/sample/thread-1001.html"
        collector._navigate = lambda *_args: (content, [event], url)  # type: ignore[method-assign]

        record = collector._fetch_post(
            object(),
            url,
            list_row={"id": 1001, "forumApp": "sample", "forumId": 9001},
        )

        self.assertEqual("visible", record["visibility"])
        self.assertEqual(200, record["raw_status"]["document_http_status"])
        self.assertEqual("content", record["raw_status"]["document_classification"])
        self.assertTrue(record["raw_status"]["detail_identity_verified"])
        self.assertTrue(record["raw_status"]["comment_identity_verified"])
        self.assertEqual("1", record["raw_status"]["comment_api_business_status"])
        self.assertEqual("have_next_false", record["raw_status"]["comment_termination"])

    def test_pure_media_detail_is_valid_without_invented_text(self) -> None:
        record = YicheCollector._detail_payload(
            (FIXTURES / "detail-media-only.html").read_text(encoding="utf-8"),
            "https://baa.yiche.com/sample/thread-1002.html",
        )

        self.assertIsNone(record["title"])
        self.assertIsNone(record["content"])
        self.assertEqual(["https://media.example.test/only.jpg"], record["image_urls"])
        self.assertEqual(["https://media.example.test/only.mp4"], record["video_urls"])
        self.assertFalse(get_platform_spec("yiche").supports_live_video_resolution)

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

        with self.assertRaises(CollectorFailure) as conflict:
            collector._parse_comments(
                "<html></html>",
                [api_event(
                    "/web_api/information_api/api/v1/comment/top_comment_list",
                    payload,
                    content_id="1001",
                )],
                12,
                "1001",
            )
        self.assertEqual("COMMENTS_TERMINATION_CONFLICT", conflict.exception.code)
        payload["data"]["total"] = 21
        with self.assertRaises(CollectorFailure) as caught:
            collector._parse_comments(
                "<html></html>",
                [api_event(
                    "/web_api/information_api/api/v1/comment/top_comment_list",
                    payload,
                    content_id="1001",
                )],
                12,
                "1001",
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

        result = collector._parse_comments(
            "<html></html>",
            [api_event(
                "/web_api/information_api/api/v1/comment/top_comment_list",
                payload,
                content_id="1001",
            )],
            12,
            "1001",
        )

        self.assertEqual(10, len(result.comments))
        self.assertEqual("c9", result.comments[-1]["platform_comment_id"])
        self.assertEqual("cap_10", result.termination)

    def test_comment_boundary_requires_api_identity_and_terminal_proof(self) -> None:
        collector = YicheCollector(None)
        path = "/web_api/information_api/api/v1/comment/top_comment_list"
        terminal_payload = {
            "status": "1",
            "data": {
                "currentPage": 1,
                "pageSize": 20,
                "total": 1,
                "list": [{"id": "c1", "contentData": {"contentText": "一级评论"}}],
            },
        }

        result = collector._parse_comments(
            "<html></html>",
            [api_event(path, terminal_payload, content_id="1001")],
            1,
            "1001",
        )
        self.assertEqual("count_boundary", result.termination)

        empty = collector._parse_comments(
            "<html></html>",
            [api_event(path, {"status": "1", "data": {"list": []}}, content_id="1001")],
            0,
            "1001",
        )
        self.assertEqual([], empty.comments)
        self.assertEqual("empty_list", empty.termination)

        with self.assertRaises(CollectorFailure) as wrong_post:
            collector._parse_comments(
                "<html></html>",
                [api_event(path, terminal_payload, content_id="1002")],
                1,
                "1001",
            )
        self.assertEqual("COMMENTS_IDENTITY_MISMATCH", wrong_post.exception.code)

        with self.assertRaises(CollectorFailure) as dom_only:
            collector._parse_comments(
                '<div id="yc-commentpc-list"><div class="yc-commentpc-item">1</div></div>',
                [],
                1,
                "1001",
            )
        self.assertEqual("COMMENTS_RESPONSE_MISSING", dom_only.exception.code)

    def test_zero_reply_count_still_surfaces_comment_api_error(self) -> None:
        collector = YicheCollector(None)
        with self.assertRaises(CollectorFailure) as caught:
            collector._parse_comments(
                "<html></html>",
                [api_event(
                    "/web_api/information_api/api/v1/comment/top_comment_list",
                    {"status": "11036", "ercd": "11036", "message": "params missing"},
                )],
                0,
                "1001",
            )
        self.assertEqual("YICHE_PUBLIC_PARAMS_MISSING", caught.exception.code)

    def test_circle_validation_freezes_three_part_identity(self) -> None:
        collector = YicheCollector(None)

        @contextmanager
        def fake_page():
            yield object()

        collector._browser_page = fake_page  # type: ignore[method-assign]
        collector._list_page = lambda *_args: {  # type: ignore[method-assign]
            "list": [
                {
                    "id": 1001,
                    "forumId": 9001,
                    "forumName": "样本社区",
                    "forumApp": "sample",
                }
            ],
            "forum_id_lookup": 9001,
            "forum": {"id": 9001, "name": "样本社区", "forumApp": "sample"},
        }
        collector._fetch_post = lambda *_args, **_kwargs: {}  # type: ignore[method-assign]

        result = collector.validate_circle("https://baa.yiche.com/sample/")

        self.assertEqual("sample", result["external_id"])
        self.assertEqual(9001, result["forum_id"])
        self.assertEqual("sample", result["seo_name"])
        self.assertEqual("样本社区", result["forum_name"])

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

    def test_collection_stops_when_total_changes_after_first_page(self) -> None:
        collector = YicheCollector(None)
        pages = {
            1: {
                "list": [{"id": index, "forumApp": "sample"} for index in range(1, 51)],
                "total": 100,
            },
            2: {"list": [{"id": 51, "forumApp": "sample"}], "total": 1},
        }

        @contextmanager
        def fake_page():
            yield object()

        collector._browser_page = fake_page  # type: ignore[method-assign]
        collector._list_page = lambda _page, _source, number: pages[number]  # type: ignore[method-assign]
        collector._fetch_post = lambda _page, url, **_kwargs: {  # type: ignore[method-assign]
            "platform_post_id": normalize_post_url(url)[0],
            "url": normalize_post_url(url)[1],
        }

        with self.assertRaises(CollectorFailure) as caught:
            collector.collect_circle("https://baa.yiche.com/sample/", 51)
        self.assertEqual("LIST_TOTAL_CHANGED", caught.exception.code)
        self.assertIn("100", caught.exception.message)
        self.assertIn("1", caught.exception.message)

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
