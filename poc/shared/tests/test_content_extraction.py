"""Candidate A JSON API 内容提取测试。"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SHARED = ROOT / "poc" / "shared"
SOURCE = ROOT / "poc" / "candidate-a" / "src"
sys.path[:0] = [str(SHARED), str(SOURCE)]

MODULE_PATH = SOURCE / "content_extraction.py"
SPEC = importlib.util.spec_from_file_location("candidate_a_content_extraction", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def detail_payload(*, comment_count: int = 0, video_play_info: str = "") -> dict:
    """构造包含第一版字段的最小详情响应。"""

    return {
        "status": 0,
        "message": "success",
        "data": {
            "group_id_str": "1234567890123456789",
            "thread_title": "标题",
            "motor_title": "正文内容",
            "content_publish_time": 1_700_000_000,
            "comment_count": comment_count,
            "digg_count": 7,
            "image_urls": [{"url": "https://img.test/1.jpg"}, {"url": "https://img.test/1.jpg"}],
            "video_play_info": video_play_info,
            "operation_status": 0,
            "visibility_level": 40,
            "motor_profile_info": {"name": "作者"},
            "motor_car_info": {"source_desc": "测试车友圈"},
        },
    }


class ApiRouteTests(unittest.TestCase):
    def test_api_url_has_no_runtime_signature_or_page_document(self) -> None:
        url = MODULE.api_url("common", group_id="1234567890123456789")
        self.assertIn("/motor/pc/ugc/detail/common?", url)
        self.assertIn("group_id=1234567890123456789", url)
        self.assertNotIn("msToken", url)
        self.assertNotIn("a_bogus", url)
        self.assertNotIn("/ugc/article/", url)

    def test_api_error_classifies_login_and_captcha_before_bulk(self) -> None:
        post_id = "1234567890123456789"
        self.assertEqual(
            "login",
            MODULE.classify_api_error(
                "https://www.dongchedi.com/motor/pc/ugc/detail/common",
                200,
                "请登录".encode(),
                post_id,
            ),
        )
        self.assertEqual(
            "captcha",
            MODULE.classify_api_error(
                "https://www.dongchedi.com/motor/pc/ugc/detail/common",
                200,
                "需要验证码".encode(),
                post_id,
            ),
        )


class DetailNormalizationTests(unittest.TestCase):
    def test_extracts_all_project_fields_and_treats_empty_comments_as_complete(self) -> None:
        record = MODULE.normalize_detail(
            "https://www.dongchedi.com/ugc/article/1234567890123456789",
            detail_payload(comment_count=0),
        )
        self.assertEqual("1234567890123456789", record["platform_post_id"])
        self.assertEqual("标题", record["title"])
        self.assertEqual("作者", record["author"])
        self.assertEqual("正文内容", record["body"])
        self.assertEqual(["https://img.test/1.jpg"], record["image_urls"])
        self.assertEqual([], record["video_urls"])
        self.assertEqual(0, record["reply_count"])
        self.assertEqual(7, record["like_count"])
        self.assertEqual("测试车友圈", record["section"])
        self.assertEqual("visible", record["visible_status"])
        self.assertTrue(record["comments_complete"])
        self.assertEqual([], record["missing_fields"])

    def test_extracts_video_play_urls_without_poster_image(self) -> None:
        play_info = (
            '{"play_addr":{"url_list":["https://video.test/main.mp4"]},'
            '"poster_url":"https://img.test/poster.jpg"}'
        )
        record = MODULE.normalize_detail(
            "https://www.dongchedi.com/ugc/article/1234567890123456789",
            detail_payload(video_play_info=play_info),
        )
        self.assertEqual(["https://video.test/main.mp4"], record["video_urls"])

    def test_empty_success_payload_is_not_treated_as_a_real_post(self) -> None:
        record = MODULE.normalize_detail(
            "https://www.dongchedi.com/ugc/article/1234567890123456789",
            {"status": 0, "message": "success", "data": {}},
        )
        self.assertEqual("detail_not_found", record["error_category"])
        self.assertFalse(record["post_id_matches"])
        self.assertFalse(record["comments_complete"])
        self.assertIn("platform_post_id", record["missing_fields"])


class CommentNormalizationTests(unittest.TestCase):
    def test_extracts_only_normalized_first_level_comment_fields(self) -> None:
        page = MODULE.comment_page(
            {
                "status": 0,
                "data": {
                    "comment_data": [
                        {
                            "comment_id_str": "991",
                            "profile_info": {"name": "评论者"},
                            "text": "评论内容",
                            "create_time": 1_700_000_001,
                            "digg_count": 3,
                            "reply_data": {"reply_list": [{"comment_id": "nested"}]},
                        }
                    ],
                    "cursor": 10,
                    "has_more": False,
                    "total_count": 1,
                },
            }
        )
        self.assertTrue(page["api_ok"])
        self.assertEqual(1, len(page["comments"]))
        self.assertEqual(
            {"comment_id", "author", "content", "published_at", "like_count"},
            set(page["comments"][0]),
        )
        self.assertNotIn("reply_data", page["comments"][0])

    def test_response_payload_decodes_utf8_from_raw_bytes(self) -> None:
        class FakeResponse:
            body = '{"status":0,"data":{"name":"四川成都IT民工"}}'.encode("utf-8")

        payload = MODULE.response_payload(FakeResponse())
        self.assertEqual("四川成都IT民工", payload["data"]["name"])

    def test_final_actual_comments_are_complete_when_api_has_no_more_page(self) -> None:
        """详情计数与实际返回不一致时，不凭计数虚构缺失评论。"""

        self.assertTrue(MODULE.comment_collection_complete(collected_count=1, has_more=False))

    def test_more_page_still_requires_cursor_collection(self) -> None:
        self.assertFalse(MODULE.comment_collection_complete(collected_count=1, has_more=True))
        self.assertTrue(MODULE.comment_collection_complete(collected_count=10, has_more=True))


class SummaryTests(unittest.TestCase):
    def test_summary_distinguishes_true_empty_comments_and_request_amplification(self) -> None:
        first = MODULE.normalize_detail(
            "https://www.dongchedi.com/ugc/article/1234567890123456789",
            detail_payload(comment_count=0),
        )
        first.update({"status": "success", "request_count": 1, "duration_ms": 200})
        second = dict(first)
        second.update(
            {
                "url": "https://www.dongchedi.com/ugc/article/2234567890123456789",
                "reply_count": 1,
                "comments": [{"comment_id": "1"}],
                "request_count": 2,
                "duration_ms": 400,
            }
        )
        summary = MODULE.build_content_summary([first, second], duration_ms=1000, concurrency=2)
        self.assertEqual(2, summary["complete_count"])
        self.assertEqual(1, summary["true_empty_comment_count"])
        self.assertEqual(1.5, summary["request_amplification"])
        self.assertEqual(1, summary["single_request_count"])
        self.assertEqual(0, summary["page_document_requests"])


if __name__ == "__main__":
    unittest.main()
