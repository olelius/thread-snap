"""汽车之家适配器字段合同、分页边界和平台注册门禁测试。"""

from __future__ import annotations

import json
import unittest

from threadsnap.collectors import CollectorFailure, get_platform_spec
from threadsnap.collectors.autohome import (
    AutohomeCollector,
    VideoMediaResolution,
    normalize_post_url,
    parse_circle_url,
)


class FakeResponse:
    """提供采集器解析所需的最小 HTTP 响应表面。"""

    def __init__(self, content: bytes, url: str, status_code: int = 200):
        self.content = content
        self.url = url
        self.status_code = status_code


class AutohomeContractTests(unittest.TestCase):
    def test_registry_keeps_formal_gate_closed_but_exposes_collector(self) -> None:
        spec = get_platform_spec("autohome")

        self.assertEqual("not_integrated", spec.adapter_status)
        self.assertIsNotNone(spec.collector_factory)
        self.assertFalse(spec.supports_page_evidence)
        self.assertFalse(spec.supports_live_video_resolution)
        self.assertEqual(1, spec.max_concurrency)

        collector = AutohomeCollector(None, concurrency=99)
        self.assertEqual(1, collector.concurrency)

    def test_source_order_and_post_identity_are_normalized(self) -> None:
        replied = parse_circle_url(
            "https://club.autohome.com.cn/bbs/forum-c-8232-9.html?sort=post"
        )
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
        collector = AutohomeCollector(None)
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
        collector._list_page(parse_circle_url(
            "https://club.autohome.com.cn/bbs/forum-c-8232-1.html?sort=topic"
        ), 2)

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
        collector = AutohomeCollector(None)
        collector._get = lambda url, **_: FakeResponse(document, url)  # type: ignore[method-assign]
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
        self.assertEqual([], record["video_urls"])
        self.assertEqual(
            "response_not_observed", record["raw_status"]["video_url_resolution"]
        )
        self.assertEqual(10, len(record["comments"]))
        self.assertEqual("用户1", record["comments"][0]["author"])
        self.assertTrue(record["raw_status"]["comments_complete"])
        self.assertEqual(
            {
                "has_more": None,
                "cursor": None,
                "page_count": None,
                "next_page_disabled": False,
            },
            record["raw_status"]["comment_page_end"],
        )

    def test_single_page_marker_proves_fewer_than_ten_comments_complete(self) -> None:
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
        collector = AutohomeCollector(None)
        collector._get = lambda url, **_: FakeResponse(document, url)  # type: ignore[method-assign]

        record = collector.fetch_post(
            "https://club.autohome.com.cn/bbs/thread/dee662/115934382-1.html",
            candidate={"bbs_id": 8232, "bbs_type": "c", "is_delete": 0, "club_delete_flag": 0},
        )

        assert record is not None
        self.assertEqual([], record["comments"])
        self.assertTrue(record["raw_status"]["comments_complete"])
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
        collector = AutohomeCollector(None)
        collector._get = lambda url, **_: FakeResponse(document, url)  # type: ignore[method-assign]

        with self.assertRaises(CollectorFailure) as caught:
            collector.fetch_post(
                "https://club.autohome.com.cn/bbs/thread/dee662/115934382-1.html",
                candidate={"bbs_id": 8232, "bbs_type": "c", "video_id_hint": "VIDEO-ONLY"},
            )

        self.assertEqual("POST_CONTENT_MISSING", caught.exception.code)

    def test_verified_video_media_response_can_prove_content(self) -> None:
        document = """
        <html><body><script>
        window['__BBSINFO__'] = {"bbsId":8232,"bbs":"c"}
        window['__TOPICINFO__'] = {topicId: 115934382, topicDelete: 0};
        window.__VIDEOINFO__ = {"videoid":"VIDEO-ONLY"};
        </script><div data-vid="VIDEO-ONLY"></div>
        <span data-page-count="1"></span><a class="athm-page__next disabled"></a>
        </body></html>
        """.encode()

        class CollectorWithFrozenMediaResponse(AutohomeCollector):
            def _video_media_response(self, video_id: str) -> VideoMediaResolution:
                return VideoMediaResolution(
                    video_id=video_id,
                    video_urls=(
                        "https://media.example.test/video.mp4?signature=temporary",
                        "https://media.example.test/video.mp4?signature=temporary",
                    ),
                    response_kind="frozen-test-response",
                )

        collector = CollectorWithFrozenMediaResponse(None)
        collector._get = lambda url, **_: FakeResponse(document, url)  # type: ignore[method-assign]

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
        self.assertEqual(
            ["https://media.example.test/video.mp4?signature=temporary"],
            record["video_urls"],
        )
        self.assertEqual("visible", record["visibility"])
        self.assertEqual("resolved", record["raw_status"]["video_url_resolution"])
        self.assertEqual(
            "frozen-test-response", record["raw_status"]["video_media_response_kind"]
        )

    def test_video_media_response_rejects_mismatched_id_and_relative_url(self) -> None:
        with self.assertRaises(CollectorFailure) as mismatched:
            AutohomeCollector._parse_video_media_response(
                "EXPECTED",
                VideoMediaResolution(
                    video_id="OTHER",
                    video_urls=("https://media.example.test/video.mp4",),
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

    def test_fewer_than_ten_comments_with_more_pages_is_incomplete(self) -> None:
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
        collector = AutohomeCollector(None)
        collector._get = lambda url, **_: FakeResponse(document, url)  # type: ignore[method-assign]

        with self.assertRaises(CollectorFailure) as caught:
            collector.fetch_post(
                "https://club.autohome.com.cn/bbs/thread/dee662/115934382-1.html",
                candidate={
                    "bbs_id": 8232,
                    "bbs_type": "c",
                    "is_delete": 0,
                    "club_delete_flag": 0,
                },
            )

        self.assertEqual("POST_COMMENTS_INCOMPLETE", caught.exception.code)

    def test_explicit_delete_flag_maps_to_hidden(self) -> None:
        document = """
        <html><body><script>
        window['__BBSINFO__'] = {"bbsId":8232,"bbs":"c"}
        window['__TOPICINFO__'] = {topicId: 115934382, topicDelete: 1};
        </script><div class="post-container">仍可见的历史正文</div>
        <span data-page-count="1"></span><a class="athm-page__next disabled"></a>
        </body></html>
        """.encode()
        collector = AutohomeCollector(None)
        collector._get = lambda url, **_: FakeResponse(document, url)  # type: ignore[method-assign]

        record = collector.fetch_post(
            "https://club.autohome.com.cn/bbs/thread/dee662/115934382-1.html",
            candidate={"bbs_id": 8232, "bbs_type": "c", "is_delete": 0, "club_delete_flag": 0},
        )

        assert record is not None
        self.assertEqual("hidden", record["visibility"])

    def test_repeated_nonempty_page_stops_discovery(self) -> None:
        collector = AutohomeCollector(None)
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
        collector = AutohomeCollector(None)
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
        collector = AutohomeCollector(None)
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

    def test_screenshot_callback_is_explicitly_rejected(self) -> None:
        collector = AutohomeCollector(None)
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

        with self.assertRaises(CollectorFailure) as challenge_error:
            AutohomeCollector._detect_control(challenge)
        with self.assertRaises(CollectorFailure) as captcha_error:
            AutohomeCollector._detect_control(captcha)

        self.assertEqual("PLATFORM_CHALLENGE", challenge_error.exception.code)
        self.assertEqual("PLATFORM_CAPTCHA_REQUIRED", captcha_error.exception.code)


if __name__ == "__main__":
    unittest.main()
