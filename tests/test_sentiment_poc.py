from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from threadsnap.errors import DomainError
from threadsnap.poc.sentiment import (
    build_request,
    parse_feedback_text,
    parse_sse_lines,
    reserve_api_call,
    stable_url_hash,
)
from threadsnap.sentiment import validate_public_https_base_url


class SentimentPocTests(unittest.TestCase):
    def test_public_https_validation_accepts_proxy_fake_ip_only_for_domain(self) -> None:
        url = "https://workspace.example.test/compatible-mode/v1"
        fake_result = [(2, 1, 6, "", ("198.18.0.17", 443))]
        with patch("threadsnap.sentiment.socket.getaddrinfo", return_value=fake_result):
            self.assertEqual(url, validate_public_https_base_url(url, resolve=True))
        with self.assertRaises(DomainError):
            validate_public_https_base_url("https://198.18.0.17/v1", resolve=True)

    def test_stable_url_hash_ignores_signature_query(self) -> None:
        first = stable_url_hash("https://media.example/video.mp4?signature=one")
        second = stable_url_hash("https://media.example/video.mp4?signature=two")
        self.assertEqual(first, second)

    def test_stable_url_hash_ignores_dcarvod_cdn_host(self) -> None:
        tail = "/video/tos/cn/tos-cn-v-4eff5f/sample/"
        first = stable_url_hash(
            f"https://v3-microapp-dcar.dcarvod.com/{'a' * 32}/12345678{tail}?token=one"
        )
        second = stable_url_hash(
            f"https://v26-microapp-dcar.dcarvod.com/{'b' * 32}/87654321{tail}?token=two"
        )
        self.assertEqual(first, second)

    def test_build_request_uses_one_streaming_multimodal_call(self) -> None:
        request = build_request(
            {
                "title": "A9L 视频",
                "content": "正文",
                "image_urls": [],
                "video_urls": ["https://media.example/video.mp4?token=secret"],
            },
            "qwen3.5-omni-plus-2026-03-15",
        )
        self.assertTrue(request["stream"])
        self.assertEqual(["text"], request["modalities"])
        self.assertEqual({"type": "json_object"}, request["response_format"])
        content = request["messages"][0]["content"]
        self.assertEqual("video_url", content[0]["type"])
        self.assertEqual("text", content[-1]["type"])

    def test_parse_sse_lines_aggregates_content_and_usage(self) -> None:
        lines = [
            'data: {"choices":[{"delta":{"content":"{\\"ok\\":"}}]}',
            'data: {"choices":[{"delta":{"content":"true}"}}]}',
            'data: {"choices":[],"usage":{"total_tokens":12}}',
            "data: [DONE]",
        ]
        content, usage, chunks = parse_sse_lines(lines)
        self.assertEqual('{"ok":true}', content)
        self.assertEqual({"total_tokens": 12}, usage)
        self.assertEqual(3, len(chunks))

    def test_parse_feedback_text_marks_trailing_fence_as_local_recovery(self) -> None:
        feedback, strict, recovered = parse_feedback_text('{"ok":true}\n```')
        self.assertEqual({"ok": True}, feedback)
        self.assertFalse(strict)
        self.assertTrue(recovered)

    def test_api_call_ledger_blocks_second_reservation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.json"
            self.assertEqual(1, reserve_api_call(path, "round-one", 1))
            with self.assertRaisesRegex(RuntimeError, "预算已用尽"):
                reserve_api_call(path, "round-two", 1)
            ledger = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(1, len(ledger["calls"]))


if __name__ == "__main__":
    unittest.main()
