"""汽车之家适配器字段合同、分页边界和平台注册状态测试。"""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from threadsnap.collectors import AuthenticationRequired, CollectorFailure, get_platform_spec
from threadsnap.collectors.autohome import (
    LIKE_COUNT_URL,
    VIDEO_MEDIA_URL,
    AutohomeCollector,
    VideoMediaResolution,
    normalize_post_url,
    parse_circle_url,
)

AUTH_STATE = {
    "cookies": [
        {
            "name": "clubUserShow",
            "value": "42|0|0|fixture-user|0|0|0||2026-08-28+15%3A00%3A00|0",
            "domain": ".autohome.com.cn",
            "path": "/",
            "expires": -1,
        },
        {
            "name": "autouserid",
            "value": "42",
            "domain": ".autohome.com.cn",
            "path": "/",
            "expires": -1,
        },
        {
            "name": "sessionlogin",
            "value": "1",
            "domain": ".autohome.com.cn",
            "path": "/",
            "expires": -1,
        },
    ]
}


class FakeResponse:
    """提供采集器解析所需的最小 HTTP 响应表面。"""

    def __init__(self, content: bytes, url: str, status_code: int = 200):
        self.content = content
        self.url = url
        self.status_code = status_code


def collector_with_like(like_count: int = 7, **kwargs: object) -> AutohomeCollector:
    """让非点赞专项夹具聚焦原有字段合同。"""

    collector = AutohomeCollector(AUTH_STATE, **kwargs)
    collector._topic_like_count = lambda *_: like_count  # type: ignore[method-assign]
    return collector


def video_media_payload(video_id: str, qualities: tuple[int, ...] = (100, 200, 300, 400)) -> dict:
    """生成与固化 AHVP GPI 响应同形的最小媒体夹具。"""

    return {
        "returncode": 0,
        "message": "",
        "result": {
            "media": {
                "qualities": [
                    {
                        "copy": (
                            f"https://media.example.test/video/{video_id}-{quality}.mp4"
                            f"?key=SIGNATURE-{quality}&time=1787817312"
                        ),
                        "value": quality,
                    }
                    for quality in qualities
                ]
            }
        },
    }


class AutohomeContractTests(unittest.TestCase):
    def test_exhausted_server_errors_become_persistent_network_retry(self) -> None:
        """连续5xx必须归一为共享Worker可识别的访问错误。"""

        collector = collector_with_like()
        calls = 0

        class ServerErrorSession:
            def get(self, url: str, **_kwargs: object) -> FakeResponse:
                nonlocal calls
                calls += 1
                return FakeResponse(b"", url, status_code=503)

        collector._http_session = lambda: ServerErrorSession()  # type: ignore[method-assign]
        with patch("threadsnap.collectors.autohome.time.sleep"):
            with self.assertRaises(CollectorFailure) as caught:
                collector._get("https://club.autohome.com.cn/bbs/thread/hash/115934382-1.html")

        self.assertEqual("PLATFORM_NETWORK_ERROR", caught.exception.code)
        self.assertEqual(3, calls)

    def test_challenge_is_handed_to_formal_auth_without_stealth_navigation(self) -> None:
        """控制页保留精确触发URL并直接进入共享认证状态机。"""

        collector = collector_with_like()
        trigger_url = "https://club.autohome.com.cn/bbs/forum-c-8232-1.html?sort=post"
        request_url = "https://club-open-api.autohome.com.cn/api/fixture"
        response = FakeResponse(
            b"<html><body>verify</body></html>",
            "https://safety.autohome.com.cn/userverify?backurl=x",
        )
        calls: list[str] = []

        class FixtureSession:
            def get(self, url: str, **_kwargs: object) -> FakeResponse:
                calls.append(url)
                return response

        collector._http_session = lambda: FixtureSession()  # type: ignore[method-assign]

        with self.assertRaises(CollectorFailure) as caught:
            collector._get(request_url, recovery_url=trigger_url)

        self.assertEqual("PLATFORM_CHALLENGE", caught.exception.code)
        self.assertEqual(trigger_url, caught.exception.trigger_url)
        self.assertEqual([request_url], calls)

    def test_registry_and_collector_publish_single_concurrency_bound(self) -> None:
        spec = get_platform_spec("autohome")

        self.assertEqual("available", spec.adapter_status)
        self.assertFalse(spec.default_enabled)
        self.assertIsNotNone(spec.collector_factory)
        self.assertTrue(spec.supports_authentication)
        self.assertIn("account.autohome.com.cn", spec.login_url or "")
        self.assertFalse(spec.supports_page_evidence)
        self.assertTrue(spec.supports_live_video_resolution)
        self.assertEqual((1, 1), (spec.min_concurrency, spec.max_concurrency))

        collector = collector_with_like(concurrency=8)
        self.assertEqual(1, collector.concurrency)
        self.assertTrue(collector.supports_live_video_resolution)

    def test_source_order_and_post_identity_are_normalized(self) -> None:
        replied = parse_circle_url("https://club.autohome.com.cn/bbs/forum-c-8232-9.html?sort=post")
        published = parse_circle_url(
            "https://club.autohome.com.cn/bbs/forum-c-8232-2.html?sort=topic"
        )

        self.assertEqual("latest_reply", replied.list_order)
        self.assertEqual("latest_publish", published.list_order)
        self.assertEqual(
            "https://club.autohome.com.cn/bbs/forum-c-8232-1.html?sort=topic",
            published.url,
        )
        self.assertEqual(
            ("115934382", "https://club.autohome.com.cn/bbs/thread/dee662/115934382-1.html"),
            normalize_post_url(
                "http://club.autohome.com.cn/bbs/thread/dee662/115934382-8.html?x=1"
            ),
        )

    def test_list_api_parameters_and_structure(self) -> None:
        collector = collector_with_like()
        calls: list[tuple[str, dict[str, object]]] = []
        payload = {
            "returncode": 0,
            "message": "success",
            "result": {"total": 2539, "items": [], "seriesid": 8232},
        }

        def fake_get(url: str, **params: object) -> FakeResponse:
            calls.append((url, params))
            return FakeResponse(json.dumps(payload).encode(), url)

        collector._get = fake_get  # type: ignore[method-assign]
        collector._list_page(
            parse_circle_url("https://club.autohome.com.cn/bbs/forum-c-8232-1.html?sort=topic"), 2
        )

        self.assertEqual(2, calls[0][1]["page_num"])
        self.assertEqual(50, calls[0][1]["page_size"])
        self.assertEqual(2, calls[0][1]["club_order_type"])

    def test_detail_extracts_media_id_and_first_ten_top_level_replies(self) -> None:
        replies = "".join(
            f"""
            <li class="js-reply-floor-container" data-floor="{index}" data-reply-id="r{index}"
                data-member-id="m{index}" data-status="0">
              <div class="reply-top"><strong>2026-08-25 18:42:41</strong></div>
              <div class="reply-detail">一级回复 {index}</div>
              <div class="reply-bottom-praise"><strong>{index}</strong></div>
              <a href="/report?authorname=用户{index}">举报</a>
            </li>"""
            for index in range(1, 13)
        )
        document = f"""
        <html><head><meta charset="utf-8"><title>详情</title></head><body>
        <script>
        window['__BBSINFO__'] = {{"bbsId":8232,"bbs":"c","bbsName":"示例论坛"}}
        window['__TOPICINFO__'] = {{
          topicId: 115934382, topicTitle: '真实标题', topicMemberId: 6748179,
          topicMemberName: '发帖人', topicDelete: 0,
        }};
        window.__VIDEOINFO__ = {{"videoid":"VIDEO-1","title":"视频元数据"}};
        </script>
        <h1 class="post-title">真实标题</h1>
        <div class="post-handle-publish"><strong>发表于</strong><strong>2026-08-25 10:00:00</strong></div>
        <div class="post-container">正文第一段<img data-src="//img.example/a.jpg" />正文第二段
          <span data-vid="VIDEO-1"></span>
        </div>
        <ul id="js-reply-list-container">{replies}</ul>
        </body></html>
        """.encode()
        collector = collector_with_like()

        def fake_get(url: str, **_: object) -> FakeResponse:
            content = (
                json.dumps(video_media_payload("VIDEO-1")).encode()
                if url == VIDEO_MEDIA_URL
                else document
            )
            return FakeResponse(content, url)

        collector._get = fake_get  # type: ignore[method-assign]
        candidate = {
            "bbs_id": 8232,
            "bbs_type": "c",
            "is_delete": 0,
            "club_delete_flag": 0,
            "video_id_hint": "VIDEO-1",
            "reply_count": 12,
        }

        record = collector.fetch_post(
            "https://club.autohome.com.cn/bbs/thread/dee662/115934382-1.html",
            candidate=candidate,
        )

        assert record is not None
        self.assertEqual("visible", record["visibility"])
        self.assertIn("正文第一段", record["content"])
        self.assertEqual(["https://img.example/a.jpg"], record["image_urls"])
        self.assertEqual("VIDEO-1", record["raw_status"]["video_id"])
        self.assertEqual(4, len(record["video_urls"]))
        self.assertEqual("resolved", record["raw_status"]["video_url_resolution"])
        self.assertEqual(10, len(record["comments"]))
        self.assertEqual("用户1", record["comments"][0]["author"])
        self.assertEqual("detail_first_page_up_to_10", record["raw_status"]["comment_capture"])
        self.assertEqual(
            {
                "has_more": None,
                "cursor": None,
                "page_count": None,
                "next_page_disabled": False,
            },
            record["raw_status"]["comment_page_end"],
        )
        self.assertFalse(record["raw_status"]["cross_forum_aggregate"])
        self.assertEqual(8232, record["raw_status"]["discovery_bbs_id"])
        self.assertEqual(7, record["like_count"])
        self.assertTrue(record["raw_status"]["authenticated_session"])
        self.assertEqual("club_zan_list", record["raw_status"]["like_count_source"])

    def test_anonymous_zero_like_is_authentication_required(self) -> None:
        """匿名详情的零值是受保护占位值，不能保存为真实点赞数。"""

        collector = AutohomeCollector(None)
        collector._get = lambda *_args, **_kwargs: self.fail(  # type: ignore[method-assign]
            "未证明登录时不应请求点赞接口"
        )

        with self.assertRaises(AuthenticationRequired) as caught:
            collector._topic_like_count(
                "115934382",
                "https://club.autohome.com.cn/bbs/thread/dee662/115934382-1.html",
            )

        self.assertEqual(
            "https://club.autohome.com.cn/bbs/thread/dee662/115934382-1.html",
            caught.exception.trigger_url,
        )

    def test_authenticated_zero_like_is_preserved_as_zero(self) -> None:
        """登录详情明确返回零时必须保存数字零，而不是空值。"""

        collector = AutohomeCollector(AUTH_STATE)
        calls: list[tuple[str, dict[str, object]]] = []

        def fake_get(url: str, **params: object) -> FakeResponse:
            calls.append((url, params))
            return FakeResponse(b"[]", url)

        collector._get = fake_get  # type: ignore[method-assign]
        value = collector._topic_like_count(
            "115934382", "https://club.autohome.com.cn/bbs/thread/dee662/115934382-1.html"
        )

        self.assertEqual(0, value)
        self.assertEqual(LIKE_COUNT_URL, calls[0][0])
        self.assertEqual("115934382-0", calls[0][1]["input"])
        self.assertEqual("42", calls[0][1]["memberId"])
        self.assertIn("Referer", calls[0][1]["request_headers"])

    def test_authenticated_like_api_requires_one_valid_value(self) -> None:
        """点赞接口明确返回主帖项时只接受唯一非负整数。"""

        collector = AutohomeCollector(AUTH_STATE)
        collector._get = lambda url, **_: FakeResponse(  # type: ignore[method-assign]
            b'[{"r":115934382,"z":"invalid"}]', url
        )

        with self.assertRaises(CollectorFailure) as caught:
            collector._topic_like_count(
                "115934382",
                "https://club.autohome.com.cn/bbs/thread/dee662/115934382-1.html",
            )

        self.assertEqual("POST_LIKE_COUNT_INVALID", caught.exception.code)

    def test_authenticated_like_api_returns_dynamic_nonzero_value(self) -> None:
        """页面脚本接口返回的动态主帖点赞数覆盖HTML占位零值。"""

        collector = AutohomeCollector(AUTH_STATE)
        collector._get = lambda url, **_: FakeResponse(  # type: ignore[method-assign]
            b'[{"r":115934382,"z":19}]', url
        )

        value = collector._topic_like_count(
            "115934382",
            "https://club.autohome.com.cn/bbs/thread/dee662/115934382-1.html",
        )

        self.assertEqual(19, value)

    def test_cross_forum_feed_item_preserves_discovery_and_canonical_identity(self) -> None:
        """列表明确聚合的跨论坛帖子仍是该来源的有效快照结果。"""

        document = """
        <html><body><script>
        window['__BBSINFO__'] = {"bbsId":8563,"bbs":"c"}
        window['__TOPICINFO__'] = {topicId: 115775128, topicDelete: 0};
        </script>
        <div class="post-container">风云A9和MG07配置对比正文</div>
        <span data-page-count="1"></span><a class="athm-page__next disabled"></a>
        </body></html>
        """.encode()
        collector = collector_with_like()
        source = parse_circle_url("https://club.autohome.com.cn/bbs/forum-c-8232-1.html?sort=post")
        candidate = collector._candidate(
            source,
            {
                "club_bbs_id": 8232,
                "club_bbs_type": "c",
                "biz_id": 115775128,
                "pc_url": (
                    "https://club.autohome.com.cn/bbs/thread/2d98dc568bd67abb/115775128-1.html"
                ),
                "app_url": ("autohome://club/topicdetail?pageid=115775128&bbsid=8563&bbstype=c"),
            },
            6,
        )
        collector._get = lambda url, **_: FakeResponse(document, url)  # type: ignore[method-assign]

        record = collector.fetch_post(candidate["url"], candidate=candidate)

        assert record is not None
        self.assertEqual(8232, record["raw_status"]["discovery_bbs_id"])
        self.assertEqual("c", record["raw_status"]["discovery_bbs_type"])
        self.assertEqual(8563, record["raw_status"]["bbs_id"])
        self.assertEqual("c", record["raw_status"]["bbs_type"])
        self.assertTrue(record["raw_status"]["cross_forum_aggregate"])
        self.assertEqual(6, candidate["order_index"])

    def test_cross_forum_feed_item_still_rejects_canonical_identity_mismatch(self) -> None:
        """列表已声明的原始论坛与详情再次冲突时仍按错帖失败关闭。"""

        document = """
        <html><body><script>
        window['__BBSINFO__'] = {"bbsId":8666,"bbs":"c"}
        window['__TOPICINFO__'] = {topicId: 115775128, topicDelete: 0};
        </script><div class="post-container">正文</div>
        <span data-page-count="1"></span><a class="athm-page__next disabled"></a>
        </body></html>
        """.encode()
        collector = collector_with_like()
        source = parse_circle_url("https://club.autohome.com.cn/bbs/forum-c-8232-1.html?sort=post")
        candidate = collector._candidate(
            source,
            {
                "club_bbs_id": 8232,
                "club_bbs_type": "c",
                "biz_id": 115775128,
                "pc_url": (
                    "https://club.autohome.com.cn/bbs/thread/2d98dc568bd67abb/115775128-1.html"
                ),
                "app_url": ("autohome://club/topicdetail?pageid=115775128&bbsid=8563&bbstype=c"),
            },
            6,
        )
        collector._get = lambda url, **_: FakeResponse(document, url)  # type: ignore[method-assign]

        with self.assertRaises(CollectorFailure) as caught:
            collector.fetch_post(candidate["url"], candidate=candidate)

        self.assertEqual("WRONG_POST", caught.exception.code)

    def test_cross_forum_detail_without_list_proof_is_rejected(self) -> None:
        """列表没有声明聚合身份时，不把普通论坛错配误当成跨论坛聚合。"""

        document = """
        <html><body><script>
        window['__BBSINFO__'] = {"bbsId":8563,"bbs":"c"}
        window['__TOPICINFO__'] = {topicId: 115775128, topicDelete: 0};
        </script><div class="post-container">正文</div>
        <span data-page-count="1"></span><a class="athm-page__next disabled"></a>
        </body></html>
        """.encode()
        collector = collector_with_like()
        collector._get = lambda url, **_: FakeResponse(document, url)  # type: ignore[method-assign]

        with self.assertRaises(CollectorFailure) as caught:
            collector.fetch_post(
                "https://club.autohome.com.cn/bbs/thread/2d98dc568bd67abb/115775128-1.html",
                candidate={"bbs_id": 8232, "bbs_type": "c"},
            )

        self.assertEqual("WRONG_POST", caught.exception.code)

    def test_single_page_marker_is_kept_as_comment_page_evidence(self) -> None:
        document = """
        <html><body><script>
        window['__BBSINFO__'] = {"bbsId":8232,"bbs":"c"}
        window['__TOPICINFO__'] = {topicId: 115934382, topicDelete: 0};
        </script>
        <div class="post-container">正文</div>
        <ul id="js-reply-list-container"></ul>
        <span class="athm-page__count" data-page-count="1">共1页</span>
        <a class="athm-page__next disabled" data-page="2">下一页</a>
        </body></html>
        """.encode()
        collector = collector_with_like()
        collector._get = lambda url, **_: FakeResponse(document, url)  # type: ignore[method-assign]

        record = collector.fetch_post(
            "https://club.autohome.com.cn/bbs/thread/dee662/115934382-1.html",
            candidate={"bbs_id": 8232, "bbs_type": "c", "is_delete": 0, "club_delete_flag": 0},
        )

        assert record is not None
        self.assertEqual([], record["comments"])
        self.assertEqual("detail_first_page_up_to_10", record["raw_status"]["comment_capture"])
        self.assertEqual(
            {
                "has_more": False,
                "cursor": None,
                "page_count": 1,
                "next_page_disabled": True,
            },
            record["raw_status"]["comment_page_end"],
        )

    def test_title_or_unresolved_video_id_is_not_content_proof(self) -> None:
        document = """
        <html><body><script>
        window['__BBSINFO__'] = {"bbsId":8232,"bbs":"c"}
        window['__TOPICINFO__'] = {
          topicId: 115934382, topicTitle: '仅标题', topicDelete: 0,
        };
        window.__VIDEOINFO__ = {"videoid":"VIDEO-ONLY"};
        </script><h1 class="post-title">仅标题</h1></body></html>
        """.encode()

        class CollectorWithoutObservedMediaResponse(AutohomeCollector):
            def _video_media_response(self, video_id: str) -> None:
                _ = video_id
                return None

        collector = CollectorWithoutObservedMediaResponse(AUTH_STATE)
        collector._topic_like_count = lambda *_: 7  # type: ignore[method-assign]
        collector._get = lambda url, **_: FakeResponse(document, url)  # type: ignore[method-assign]

        with self.assertRaises(CollectorFailure) as caught:
            collector.fetch_post(
                "https://club.autohome.com.cn/bbs/thread/dee662/115934382-1.html",
                candidate={"bbs_id": 8232, "bbs_type": "c", "video_id_hint": "VIDEO-ONLY"},
            )

        self.assertEqual("POST_CONTENT_MISSING", caught.exception.code)

    def test_real_video_response_contract_can_prove_video_only_content(self) -> None:
        document = """
        <html><body><script>
        window['__BBSINFO__'] = {"bbsId":8232,"bbs":"c"}
        window['__TOPICINFO__'] = {topicId: 115934382, topicDelete: 0};
        window.__VIDEOINFO__ = {"videoid":"VIDEO-ONLY"};
        </script><div data-vid="VIDEO-ONLY"></div>
        <span data-page-count="1"></span><a class="athm-page__next disabled"></a>
        </body></html>
        """.encode()

        calls: list[tuple[str, dict[str, object]]] = []
        collector = collector_with_like()

        def fake_get(url: str, **params: object) -> FakeResponse:
            calls.append((url, params))
            content = (
                json.dumps(video_media_payload("VIDEO-ONLY")).encode()
                if url == VIDEO_MEDIA_URL
                else document
            )
            return FakeResponse(content, url)

        collector._get = fake_get  # type: ignore[method-assign]

        record = collector.fetch_post(
            "https://club.autohome.com.cn/bbs/thread/dee662/115934382-1.html",
            candidate={
                "bbs_id": 8232,
                "bbs_type": "c",
                "is_delete": 0,
                "club_delete_flag": 0,
                "video_id_hint": "VIDEO-ONLY",
            },
        )

        assert record is not None
        self.assertIsNone(record["content"])
        self.assertEqual([], record["image_urls"])
        self.assertEqual(4, len(record["video_urls"]))
        self.assertTrue(all("VIDEO-ONLY-" in url for url in record["video_urls"]))
        self.assertEqual("visible", record["visibility"])
        self.assertEqual("resolved", record["raw_status"]["video_url_resolution"])
        self.assertEqual("ahvp-gpi-v1", record["raw_status"]["video_media_response_kind"])
        self.assertEqual(
            (VIDEO_MEDIA_URL, {"mid": "VIDEO-ONLY", "ft": "mp4", "strategy": 1}),
            calls[1],
        )

    def test_video_media_response_rejects_mismatched_id_and_relative_url(self) -> None:
        with self.assertRaises(CollectorFailure) as mismatched:
            AutohomeCollector._parse_video_media_response(
                "EXPECTED",
                VideoMediaResolution(
                    video_id="OTHER",
                    video_urls=("https://media.example.test/OTHER-300.mp4?key=SIGNATURE",),
                    response_kind="frozen-test-response",
                ),
            )
        with self.assertRaises(CollectorFailure) as invalid_url:
            AutohomeCollector._parse_video_media_response(
                "EXPECTED",
                VideoMediaResolution(
                    video_id="EXPECTED",
                    video_urls=("/video.mp4",),
                    response_kind="frozen-test-response",
                ),
            )

        self.assertEqual("POST_VIDEO_ID_MISMATCH", mismatched.exception.code)
        self.assertEqual("PLATFORM_RESPONSE_INVALID", invalid_url.exception.code)

    def test_video_media_control_failure_is_not_reclassified(self) -> None:
        collector = collector_with_like()

        def blocked(_url: str, **_: object) -> FakeResponse:
            raise CollectorFailure("PLATFORM_CHALLENGE", "访问验证")

        collector._get = blocked  # type: ignore[method-assign]
        with self.assertRaises(CollectorFailure) as caught:
            collector._video_media_response("VIDEO-1")

        self.assertEqual("PLATFORM_CHALLENGE", caught.exception.code)

    def test_public_video_resolver_preserves_all_qualities(self) -> None:
        collector = collector_with_like()
        calls: list[tuple[str, dict[str, object]]] = []

        def fake_get(url: str, **params: object) -> FakeResponse:
            calls.append((url, params))
            payload = video_media_payload("VIDEO-1", (100, 200, 300, 400, 400))
            return FakeResponse(json.dumps(payload).encode(), url)

        collector._get = fake_get  # type: ignore[method-assign]

        urls = collector.resolve_video_urls(" VIDEO-1 ")

        self.assertEqual(4, len(urls))
        self.assertEqual(4, len(set(urls)))
        self.assertEqual(
            [(VIDEO_MEDIA_URL, {"mid": "VIDEO-1", "ft": "mp4", "strategy": 1})],
            calls,
        )
        self.assertEqual([], collector.resolve_video_urls(""))

    def test_video_media_rejects_nonzero_and_invalid_structure(self) -> None:
        collector = collector_with_like()
        invalid_payloads = (
            (
                {"returncode": 1001, "message": "failed", "result": {}},
                "VIDEO_MEDIA_RESPONSE_ERROR",
            ),
            (
                {"returncode": 0, "message": "", "result": {"media": {"qualities": {}}}},
                "VIDEO_MEDIA_RESPONSE_INVALID",
            ),
        )
        for payload, expected_code in invalid_payloads:
            with self.subTest(expected_code=expected_code):
                collector._get = lambda url, **_: FakeResponse(  # type: ignore[method-assign]
                    json.dumps(payload).encode(), url
                )
                with self.assertRaises(CollectorFailure) as caught:
                    collector._video_media_response("VIDEO-1")
                self.assertEqual(expected_code, caught.exception.code)

    def test_video_media_rejects_quality_without_copy(self) -> None:
        collector = collector_with_like()
        payload = video_media_payload("VIDEO-1")
        payload["result"]["media"]["qualities"][2].pop("copy")
        collector._get = lambda url, **_: FakeResponse(  # type: ignore[method-assign]
            json.dumps(payload).encode(), url
        )

        with self.assertRaises(CollectorFailure) as caught:
            collector._video_media_response("VIDEO-1")

        self.assertEqual("VIDEO_MEDIA_URL_MISSING", caught.exception.code)

    def test_fewer_than_ten_comments_with_more_pages_still_keeps_post(self) -> None:
        document = """
        <html><body><script>
        window['__BBSINFO__'] = {"bbsId":8232,"bbs":"c"}
        window['__TOPICINFO__'] = {topicId: 115934382, topicDelete: 0};
        </script>
        <div class="post-container">正文</div>
        <ul id="js-reply-list-container">
          <li class="js-reply-floor-container" data-reply-id="r1">
            <div class="reply-detail">第一页一级回复</div>
          </li>
        </ul>
        <span data-page-count="2">共2页</span>
        <a class="athm-page__next" data-page="2">下一页</a>
        </body></html>
        """.encode()
        collector = collector_with_like()
        collector._get = lambda url, **_: FakeResponse(document, url)  # type: ignore[method-assign]

        record = collector.fetch_post(
            "https://club.autohome.com.cn/bbs/thread/dee662/115934382-1.html",
            candidate={
                "bbs_id": 8232,
                "bbs_type": "c",
                "is_delete": 0,
                "club_delete_flag": 0,
            },
        )

        assert record is not None
        self.assertEqual(1, len(record["comments"]))
        self.assertEqual("detail_first_page_up_to_10", record["raw_status"]["comment_capture"])

    def test_explicit_delete_flag_maps_to_hidden(self) -> None:
        document = """
        <html><body><script>
        window['__BBSINFO__'] = {"bbsId":8232,"bbs":"c"}
        window['__TOPICINFO__'] = {topicId: 115934382, topicDelete: 1};
        </script><div class="post-container">仍可见的历史正文</div>
        <span data-page-count="1"></span><a class="athm-page__next disabled"></a>
        </body></html>
        """.encode()
        collector = collector_with_like()
        collector._get = lambda url, **_: FakeResponse(document, url)  # type: ignore[method-assign]

        record = collector.fetch_post(
            "https://club.autohome.com.cn/bbs/thread/dee662/115934382-1.html",
            candidate={"bbs_id": 8232, "bbs_type": "c", "is_delete": 0, "club_delete_flag": 0},
        )

        assert record is not None
        self.assertEqual("hidden", record["visibility"])

    def test_repeated_nonempty_page_stops_discovery(self) -> None:
        collector = collector_with_like()
        item = {
            "club_bbs_id": 8232,
            "club_bbs_type": "c",
            "biz_id": 115934382,
            "pc_url": "https://club.autohome.com.cn/bbs/thread/dee662/115934382-1.html",
        }
        calls = 0

        def repeated_page(_source: object, _page: int) -> dict:
            nonlocal calls
            calls += 1
            return {"items": [item], "total": None, "series_id": 8232}

        collector._list_page = repeated_page  # type: ignore[method-assign]
        rows, reason = collector.discover_posts(
            "https://club.autohome.com.cn/bbs/forum-c-8232-1.html?sort=post", 2
        )

        self.assertEqual(1, len(rows))
        self.assertEqual(2, calls)
        self.assertIn("重复", reason)

    def test_control_response_halts_import_without_visiting_later_urls(self) -> None:
        collector = collector_with_like()
        visited: list[str] = []

        def blocked(url: str, **_: object) -> None:
            visited.append(url)
            raise CollectorFailure("PLATFORM_CHALLENGE", "访问验证")

        collector.fetch_post = blocked  # type: ignore[method-assign]
        with self.assertRaises(CollectorFailure) as caught:
            collector.collect_urls(
                [
                    "https://club.autohome.com.cn/bbs/thread/dee662/115934382-1.html",
                    "https://club.autohome.com.cn/bbs/thread/dee663/115934383-1.html",
                ]
            )

        self.assertEqual("PLATFORM_CHALLENGE", caught.exception.code)
        self.assertEqual(1, len(visited))

    def test_control_response_halts_circle_collection(self) -> None:
        collector = collector_with_like()
        items = [
            {
                "club_bbs_id": 8232,
                "club_bbs_type": "c",
                "biz_id": post_id,
                "pc_url": f"https://club.autohome.com.cn/bbs/thread/hash{post_id}/{post_id}-1.html",
            }
            for post_id in (115934382, 115934383)
        ]
        collector._list_page = lambda _source, _page: {  # type: ignore[method-assign]
            "items": items,
            "total": 2,
            "series_id": 8232,
        }
        visited: list[str] = []

        def blocked(url: str, **_: object) -> None:
            visited.append(url)
            raise CollectorFailure("PLATFORM_CAPTCHA_REQUIRED", "验证码")

        collector.fetch_post = blocked  # type: ignore[method-assign]
        with self.assertRaises(CollectorFailure) as caught:
            collector.collect_circle(
                "https://club.autohome.com.cn/bbs/forum-c-8232-1.html?sort=post", 2
            )

        self.assertEqual("PLATFORM_CAPTCHA_REQUIRED", caught.exception.code)
        self.assertEqual(1, len(visited))

    def test_rate_limit_returns_only_frozen_remaining_candidates_for_retry(self) -> None:
        """限流必须停止当前来源，并把已冻结的剩余URL交给Worker原位续跑。"""

        collector = collector_with_like()
        items = [
            {
                "club_bbs_id": 8232,
                "club_bbs_type": "c",
                "biz_id": post_id,
                "pc_url": f"https://club.autohome.com.cn/bbs/thread/hash{post_id}/{post_id}-1.html",
            }
            for post_id in (115934382, 115934383, 115934384)
        ]
        collector._list_page = lambda _source, _page: {  # type: ignore[method-assign]
            "items": items,
            "total": 3,
            "series_id": 8232,
        }
        visited: list[str] = []

        def rate_limited(url: str, **_: object) -> None:
            visited.append(normalize_post_url(url)[0])
            raise CollectorFailure("PLATFORM_RATE_LIMITED", "请求频繁")

        collector.fetch_post = rate_limited  # type: ignore[method-assign]
        result = collector.collect_circle(
            "https://club.autohome.com.cn/bbs/forum-c-8232-1.html?sort=post", 2
        )

        self.assertEqual(["115934382"], visited)
        self.assertEqual(
            ["115934382", "115934383"],
            [normalize_post_url(row["url"])[0] for row in result["failures"]],
        )
        self.assertEqual({"PLATFORM_RATE_LIMITED"}, {row["code"] for row in result["failures"]})
        self.assertNotIn("115934384", json.dumps(result, ensure_ascii=False))

    def test_rate_limit_stops_url_list_and_preserves_unvisited_remainder(self) -> None:
        """已知URL重试再次限流时不能访问后续项，也不能丢失剩余固定URL。"""

        collector = collector_with_like()
        urls = [
            "https://club.autohome.com.cn/bbs/thread/dee662/115934382-1.html",
            "https://club.autohome.com.cn/bbs/thread/dee663/115934383-1.html",
        ]
        visited: list[str] = []

        def rate_limited(url: str, **_: object) -> None:
            visited.append(url)
            raise CollectorFailure("PLATFORM_RATE_LIMITED", "请求频繁")

        collector.fetch_post = rate_limited  # type: ignore[method-assign]
        result = collector.collect_urls(urls)

        self.assertEqual([urls[0]], visited)
        self.assertEqual(urls, [row["url"] for row in result["failures"]])
        self.assertEqual({"PLATFORM_RATE_LIMITED"}, {row["code"] for row in result["failures"]})

    def test_failed_fixed_candidate_is_not_replaced_by_later_row(self) -> None:
        """圈子前 N 个候选一旦冻结，详情失败也不得向后补位。"""

        collector = collector_with_like()
        items = [
            {
                "club_bbs_id": 8232,
                "club_bbs_type": "c",
                "biz_id": post_id,
                "pc_url": f"https://club.autohome.com.cn/bbs/thread/hash{post_id}/{post_id}-1.html",
            }
            for post_id in (115934382, 115934383, 115934384)
        ]
        collector._list_page = lambda _source, _page: {  # type: ignore[method-assign]
            "items": items,
            "total": 3,
            "series_id": 8232,
        }
        visited: list[str] = []

        def fetch(url: str, **_: object) -> dict:
            post_id, normalized_url = normalize_post_url(url)
            visited.append(post_id)
            if post_id == "115934382":
                raise CollectorFailure("POST_CONTENT_EMPTY", "固定候选正文为空")
            return {"platform_post_id": post_id, "url": normalized_url}

        collector.fetch_post = fetch  # type: ignore[method-assign]
        result = collector.collect_circle(
            "https://club.autohome.com.cn/bbs/forum-c-8232-1.html?sort=post", 2
        )

        self.assertEqual(["115934382", "115934383"], visited)
        self.assertEqual(["115934383"], [row["platform_post_id"] for row in result["records"]])
        self.assertEqual(
            ["115934382"],
            [normalize_post_url(row["url"])[0] for row in result["failures"]],
        )
        self.assertIn("未使用后续帖子替换", result["stop_reason"])

    def test_screenshot_callback_is_explicitly_rejected(self) -> None:
        collector = collector_with_like()
        with self.assertRaisesRegex(CollectorFailure, "截图") as caught:
            collector.collect_circle(
                "https://club.autohome.com.cn/bbs/forum-c-8232-1.html?sort=post",
                1,
                on_page_evidence=lambda _: None,
            )
        self.assertEqual("PAGE_EVIDENCE_UNSUPPORTED", caught.exception.code)

    def test_userverify_is_challenge_but_visible_captcha_takes_priority(self) -> None:
        challenge = FakeResponse(
            b"<html><title>user verify</title><body>verify</body></html>",
            "https://safety.autohome.com.cn/userverify?backurl=x",
        )
        captcha = FakeResponse(
            b"<html><body>captcha</body></html>",
            "https://safety.autohome.com.cn/userverify?backurl=x",
        )
        trigger_url = "https://club.autohome.com.cn/bbs/forum-c-7853-1.html?sort=post"

        with self.assertRaises(CollectorFailure) as challenge_error:
            AutohomeCollector._detect_control(challenge, trigger_url=trigger_url)
        with self.assertRaises(CollectorFailure) as captcha_error:
            AutohomeCollector._detect_control(captcha, trigger_url=trigger_url)

        self.assertEqual("PLATFORM_CHALLENGE", challenge_error.exception.code)
        self.assertEqual("PLATFORM_CAPTCHA_REQUIRED", captcha_error.exception.code)
        self.assertEqual(trigger_url, challenge_error.exception.trigger_url)
        self.assertEqual(trigger_url, captcha_error.exception.trigger_url)


if __name__ == "__main__":
    unittest.main()
