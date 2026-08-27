"""汽车之家适配器字段合同、分页边界和平台注册门禁测试。"""

from __future__ import annotations

import json
import unittest

from threadsnap.collectors import CollectorFailure, get_platform_spec
from threadsnap.collectors.autohome import (
    AutohomeCollector,
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
        self.assertEqual(10, len(record["comments"]))
        self.assertEqual("用户1", record["comments"][0]["author"])

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
