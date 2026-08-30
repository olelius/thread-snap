"""平台中立采集契约与易车已确认入口事实。"""

from __future__ import annotations

import unittest
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
        spec = get_platform_spec("dongchedi")

        self.assertEqual("懂车帝", spec.display_name)
        self.assertEqual((1, 2000), (spec.min_quantity, spec.max_quantity))
        self.assertEqual(
            (1, 2, 8),
            (
                spec.min_concurrency,
                spec.default_concurrency,
                spec.max_concurrency,
            ),
        )
        self.assertTrue(spec.default_enabled)
        self.assertEqual("available", spec.adapter_status)
        self.assertTrue(spec.supports_page_evidence)
        self.assertEqual("direct_http", spec.background_transport)

    def test_yiche_spec_uses_shared_concurrency_bounds(self) -> None:
        spec = get_platform_spec("yiche")

        self.assertEqual("易车", spec.display_name)
        self.assertEqual((1, 500), (spec.min_quantity, spec.max_quantity))
        self.assertEqual(
            (1, 1, 8),
            (
                spec.min_concurrency,
                spec.default_concurrency,
                spec.max_concurrency,
            ),
        )
        self.assertFalse(spec.default_enabled)
        self.assertEqual("available", spec.adapter_status)
        self.assertFalse(spec.supports_page_evidence)
        self.assertEqual("account_login", spec.authentication_mode)
        self.assertEqual("direct_http", spec.background_transport)


class YicheKnownFactsTests(unittest.TestCase):
    @staticmethod
    def _logged_state() -> dict:
        return {
            "cookies": [
                {
                    "name": "username",
                    "value": "fixture",
                    "domain": ".yiche.com",
                    "path": "/",
                    "expires": -1,
                }
            ]
        }

    def test_comment_request_keeps_only_content_identity(self) -> None:
        self.assertEqual(
            "1001",
            _request_content_id(
                "https://api.example.test/comment?param=%7B%22contentId%22%3A1001%7D"
            ),
        )

    def test_naive_platform_time_is_attached_to_asia_shanghai(self) -> None:
        parsed = _parse_time("2026-08-27 10:20:30")
        assert parsed is not None
        self.assertEqual(8 * 3600, int(parsed.utcoffset().total_seconds()))
        self.assertEqual(2, parsed.astimezone(timezone.utc).hour)

    def test_circle_and_post_urls_normalize_to_stable_identity(self) -> None:
        source = parse_circle_url("https://baa.yiche.com/sample/index-0-1-2.html?tag=-1")
        self.assertEqual(("sample", "latest_publish"), (source.external_id, source.list_order))
        self.assertEqual("https://baa.yiche.com/sample/index-0-1-1.html?tag=-1", source.url)
        self.assertEqual(
            ("1001", "https://baa.yiche.com/sample/thread-1001.html"),
            normalize_post_url("https://baa.yiche.com/sample/thread-1001.html?x=1"),
        )

    def test_account_login_is_required_before_collection(self) -> None:
        with self.assertRaises(AuthenticationRequired):
            YicheCollector(None).collect_urls(["https://baa.yiche.com/sample/thread-1001.html"])

    def test_account_identity_api_completes_login_gate(self) -> None:
        collector = YicheCollector(self._logged_state())
        collector._api_event = lambda *_args, **_kwargs: api_event(
            "/web_api/user_center_api/api/v1/message/get_message_num",
            {"status": "1", "data": {"userId": 42, "showName": "fixture"}},
        )

        self.assertTrue(
            collector.validate_auth("https://baa.yiche.com/sample/")["account_login_verified"]
        )

    def test_signature_is_stable_for_known_timestamp(self) -> None:
        params, headers = YicheCollector._signed_request({"forumId": 9001}, 1700000000000)
        self.assertEqual(("508", '{"forumId":9001}'), (params["cid"], params["param"]))
        self.assertRegex(headers["x-sign"], r"^[0-9a-f]{32}$")
        self.assertEqual(
            (params, headers), YicheCollector._signed_request({"forumId": 9001}, 1700000000000)
        )

    def test_203_challenge_parser_is_bounded(self) -> None:
        fixture = (
            '<script>var _xvasu = 1104958252; var _xvpfs = "tws2_"; '
            'var _xvpts = 1788060021.479; document.cookie=btoa("x"); '
            "window['location'].reload();</script>"
        )
        name, value = YicheCollector._challenge_cookie(fixture)
        self.assertEqual("tws2_1104958252", name)
        self.assertTrue(value)
        with self.assertRaises(CollectorFailure) as caught:
            YicheCollector._challenge_cookie("<script>location.reload()</script>")
        self.assertEqual("YICHE_CHALLENGE_CHANGED", caught.exception.code)

    def test_tencent_waf_document_enters_manual_recovery(self) -> None:
        control = (
            '<script src="TCaptcha.js"></script><script>TencentCaptcha();'
            'window.__captcha=true</script><form action="/WafCaptcha"></form>'
        )
        self.assertTrue(is_waf_captcha(control))
        with self.assertRaises(AuthenticationRequired):
            require_content_page(control, url="https://baa.yiche.com/sample/")

    def test_business_errors_are_classified(self) -> None:
        with self.assertRaises(CollectorFailure) as limited:
            YicheCollector._api_payload(
                [api_event("/post/getlist", None, status=429)], "/post/getlist"
            )
        self.assertEqual("RATE_LIMITED", limited.exception.code)
        with self.assertRaises(CollectorFailure) as unsigned:
            YicheCollector._api_payload(
                [api_event("/post/getlist", {"status": "11036", "ercd": "11036"})], "/post/getlist"
            )
        self.assertEqual("YICHE_PUBLIC_PARAMS_MISSING", unsigned.exception.code)

    def test_detail_uses_structured_text_and_original_media(self) -> None:
        record = YicheCollector._detail_payload(
            (FIXTURES / "detail.html").read_text("utf-8"),
            "https://baa.yiche.com/sample/thread-1001.html",
        )
        self.assertEqual("1001", record["platform_post_id"])
        self.assertEqual("结构化正文第一段。\n结构化正文第二段。", record["content"])
        self.assertEqual(3, record["like_count"])
        self.assertEqual("unknown", record["visibility"])

    def test_detail_identity_and_obfuscation_fail_closed(self) -> None:
        fixture = (FIXTURES / "detail.html").read_text("utf-8")
        with self.assertRaises(CollectorFailure) as wrong:
            YicheCollector._detail_payload(fixture, "https://baa.yiche.com/wrong/thread-1001.html")
        self.assertEqual("POST_IDENTITY_MISMATCH", wrong.exception.code)
        with self.assertRaises(CollectorFailure) as obfuscated:
            YicheCollector._detail_payload(
                fixture.replace("结构化正文第一段。", "结构化\ue123正文。"),
                "https://baa.yiche.com/sample/thread-1001.html",
            )
        self.assertEqual("POST_CONTENT_OBFUSCATED", obfuscated.exception.code)

    def test_comment_mapping_keeps_post_data_when_comment_identity_does_not_match(self) -> None:
        collector = YicheCollector(None)
        path = "/web_api/information_api/api/v1/comment/top_comment_list"
        payload = {
            "status": "1",
            "data": {
                "currentPage": 1,
                "pageSize": 20,
                "total": 1,
                "haveNextPage": False,
                "list": [{"id": "c1", "contentData": {"contentText": "一级评论"}}],
            },
        }
        result = collector._parse_comments(
            "", [api_event(path, payload, content_id="1001")], 1, "1001"
        )
        self.assertEqual((1, "have_next_false"), (len(result.comments), result.termination))
        wrong = collector._parse_comments(
            "", [api_event(path, payload, content_id="1002")], 1, "1001"
        )
        self.assertEqual(([], "first_page", False), (wrong.comments, wrong.termination, wrong.verified))

    def test_circle_validation_freezes_three_part_identity_over_http(self) -> None:
        collector = YicheCollector(self._logged_state())
        collector._account_verified = True
        collector._list_page = lambda *_args: {
            "list": [{"id": 1001, "forumId": 9001, "forumName": "样本社区", "forumApp": "sample"}],
            "forum_id_lookup": 9001,
            "forum": {"id": 9001, "name": "样本社区", "forumApp": "sample"},
        }
        collector._fetch_post = lambda *_args, **_kwargs: {}
        result = collector.validate_circle("https://baa.yiche.com/sample/")
        self.assertEqual((9001, "sample"), (result["forum_id"], result["seo_name"]))

    def test_collection_crosses_http_pages_and_honors_checkpoint(self) -> None:
        collector = YicheCollector(self._logged_state())
        collector._account_verified = True
        pages = {
            1: {"list": [{"id": 1001}, {"id": 1002}], "total": 51},
            2: {"list": [{"id": 1003}], "total": 51},
        }
        visited: list[int] = []
        collector._list_page = lambda _source, page: visited.append(page) or pages[page]
        collector._fetch_post = lambda url, **_kwargs: {
            "platform_post_id": normalize_post_url(url)[0],
            "url": normalize_post_url(url)[1],
        }
        result = collector.collect_circle(
            "https://baa.yiche.com/sample/", 2, skip_post_ids={"1001"}
        )
        self.assertEqual(["1002", "1003"], [x["platform_post_id"] for x in result["records"]])
        self.assertEqual([1, 2], visited)

    def test_comment_mapping_is_capped_at_ten(self) -> None:
        rows = [{"id": f"c{i}", "contentData": {"contentText": f"评论{i}"}} for i in range(12)]
        payload = {"status": "1", "data": {"haveNextPage": True, "list": rows}}
        result = YicheCollector(None)._parse_comments(
            "", [api_event("/comment/top_comment_list", payload, content_id="1001")], 12, "1001"
        )
        self.assertEqual((10, "cap_10"), (len(result.comments), result.termination))

    def test_comment_continuation_and_count_conflict_keep_first_page(self) -> None:
        payload = {
            "status": "1",
            "data": {
                "currentPage": 1,
                "pageSize": 20,
                "total": 1,
                "haveNextPage": True,
                "list": [{"id": "c1"}],
            },
        }
        conflict = YicheCollector(None)._parse_comments(
            "", [api_event("/comment/top_comment_list", payload, content_id="1001")], 1, "1001"
        )
        self.assertEqual((1, "first_page"), (len(conflict.comments), conflict.termination))
        payload["data"]["total"] = 21
        continued = YicheCollector(None)._parse_comments(
            "", [api_event("/comment/top_comment_list", payload, content_id="1001")], 21, "1001"
        )
        self.assertEqual((1, "first_page"), (len(continued.comments), continued.termination))

    def test_comment_empty_and_missing_responses_both_keep_post_result(self) -> None:
        collector = YicheCollector(None)
        empty = collector._parse_comments(
            "",
            [
                api_event(
                    "/comment/top_comment_list",
                    {"status": "1", "data": {"list": []}},
                    content_id="1001",
                )
            ],
            0,
            "1001",
        )
        self.assertEqual("empty_list", empty.termination)
        missing = collector._parse_comments("", [], 0, "1001")
        self.assertEqual(([], "first_page", False), (missing.comments, missing.termination, missing.verified))

    def test_account_identity_without_user_id_stays_unverified(self) -> None:
        collector = YicheCollector(self._logged_state())
        collector._api_event = lambda *_args, **_kwargs: api_event(
            "/message/get_message_num", {"status": "1", "data": {}}
        )
        with self.assertRaises(AuthenticationRequired):
            collector.validate_auth("https://baa.yiche.com/sample/")
        self.assertFalse(collector._account_verified)

    def test_list_page_freezes_forum_identity_and_page_size(self) -> None:
        collector = YicheCollector(self._logged_state())
        calls: list[dict] = []

        def event(url: str, data: dict, **_kwargs: object) -> ApiEvent:
            calls.append(data)
            if url.endswith("/getid"):
                return api_event("/forum/getid", {"status": "1", "data": 9001})
            if url.endswith("/get"):
                return api_event("/forum/get", {"status": "1", "data": {"id": 9001}})
            return api_event(
                "/post/getlist", {"status": "1", "data": {"list": [{"id": 1001}], "total": 1}}
            )

        collector._api_event = event
        page = collector._list_page(parse_circle_url("https://baa.yiche.com/sample/"), 1)
        self.assertEqual((9001, 1), (page["forum_id_lookup"], len(page["list"])))
        self.assertIn(
            {"forumId": 9001, "order": 0, "pageIndex": 1, "pageSize": 50, "tagId": -1}, calls
        )

    def test_collection_stops_when_http_total_changes(self) -> None:
        collector = YicheCollector(self._logged_state())
        collector._account_verified = True
        pages = {
            1: {"list": [{"id": i} for i in range(1, 51)], "total": 100},
            2: {"list": [{"id": 51}], "total": 1},
        }
        collector._list_page = lambda _source, page: pages[page]
        collector._fetch_post = lambda url, **_kwargs: {
            "platform_post_id": normalize_post_url(url)[0],
            "url": url,
        }
        with self.assertRaises(CollectorFailure) as caught:
            collector.collect_circle("https://baa.yiche.com/sample/", 51)
        self.assertEqual("LIST_TOTAL_CHANGED", caught.exception.code)

    def test_authentication_preserves_completed_http_checkpoint(self) -> None:
        collector = YicheCollector(self._logged_state())
        collector._account_verified = True
        collector._list_page = lambda *_args: {"list": [{"id": 1001}, {"id": 1002}], "total": 2}

        def fetch(url: str, **_kwargs: object) -> dict:
            post_id = normalize_post_url(url)[0]
            if post_id == "1002":
                raise AuthenticationRequired("fixture", trigger_url=url)
            return {"platform_post_id": post_id, "url": url}

        collector._fetch_post = fetch
        with self.assertRaises(AuthenticationRequired) as caught:
            collector.collect_circle("https://baa.yiche.com/sample/", 2)
        self.assertEqual(["1001"], [x["platform_post_id"] for x in caught.exception.records])

    def test_url_collection_deduplicates_normalized_post_identity(self) -> None:
        collector = YicheCollector(self._logged_state())
        collector._account_verified = True
        collector._fetch_post = lambda url, **_kwargs: {
            "platform_post_id": normalize_post_url(url)[0],
            "url": url,
        }
        result = collector.collect_urls(
            [
                "https://baa.yiche.com/sample/thread-1001.html",
                "https://baa.yiche.com/sample/thread-1001.html?again=1",
            ]
        )
        self.assertEqual(1, len(result["records"]))


if __name__ == "__main__":
    unittest.main()
