"""懂车帝合法缺评价篇数与真实结构错误的浏览器/HTTP合同回归。"""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock

from PIL import Image

from threadsnap.reputation import ReputationService
from threadsnap.reputation_adapter import ReputationAdapterError, ReputationMappingTarget
from threadsnap.reputation_dongchedi import DongchediReputationAdapter


class DongchediOptionalMetricTests(unittest.IsolatedAsyncioTestCase):
    """使用同一已识别车型页证明可选缺失不阻断独立指标和证据。"""

    def setUp(self):
        self.target = ReputationMappingTarget(
            "fixture-optional",
            "100",
            "https://www.dongchedi.com/auto/series/100",
            "测试车型",
            "fixture-hash",
        )
        self.rate_url = "https://api.dcarapi.com/motor/car_score/api/v1/landing_page/get_detail/"
        self.adapter = DongchediReputationAdapter(
            None,
            include_review_article_count=True,
            include_negative_rate=True,
        )

    def _http(self, next_data, *, name="测试车型"):
        """保留实际HTTP解析和差评率解析，仅替换网络响应。"""

        script = (
            ""
            if next_data is None
            else f'<script id="__NEXT_DATA__" type="application/json">{next_data}</script>'
        )
        body = f"""<html><body><h1>{name}</h1><span>共1,234人评价</span>
          <div class="rank-wrapper"><ul><li class="tw-text-common-yellow">
            <span class="car-name">{name}</span><span class="score-wrapper">3.90</span>
          </li></ul></div>{script}</body></html>""".encode()
        page = Mock(status_code=200, url=self.target.platform_url, content=body)
        rate = Mock(status_code=200, url=self.rate_url)
        rate.json.return_value = {
            "data": {
                "series_info": {"series_name": "测试车型"},
                "tag_info_v2": {
                    "hierarchical_tag_list": [
                        {"part_id": "3", "tag_name": "优点", "count": 214},
                        {"part_id": "4", "tag_name": "缺点", "count": 128},
                    ]
                },
            },
        }
        session = Mock()
        session.get.side_effect = lambda url, **_: rate if "dcarapi.com" in url else page
        self.adapter._http_session = Mock(return_value=session)
        return self.adapter._visit_http(self.target)

    def test_http_missing_or_null_count_keeps_other_metrics_and_source(self):
        """合法缺字段/null正常留空；0是实际评价篇数，不转成空值。"""

        for props, expected in (
            ({}, None),
            ({"reviewListData": None}, None),
            ({"reviewListData": {}}, None),
            ({"reviewListData": {"total_count": None}}, None),
            ({"reviewListData": {"total_count": 0}}, "0"),
        ):
            with self.subTest(props=props):
                result = self._http(json.dumps({"props": {"pageProps": props}}))
                self.assertEqual(expected, result.review_article_count_raw)
                self.assertEqual(self.target.platform_url, result.review_article_count_url)
                self.assertEqual(
                    ("3.90", "1", "1234"), (result.score_raw, result.rank_raw, result.volume_raw)
                )
                self.assertEqual(
                    ("37%", self.rate_url, 214, 128),
                    (
                        result.negative_rate_raw,
                        result.negative_rate_url,
                        result.negative_rate_positive_count,
                        result.negative_rate_negative_count,
                    ),
                )
                self.assertFalse(result.reputation_not_available)
                metrics = ReputationService._official_metrics(result, None)
                self.assertEqual("37", metrics["negative_rate"]["value"])
                self.assertEqual(
                    "not_available" if expected is None else "no_baseline",
                    metrics["review_article_count"]["comparison_status"],
                )

    def test_http_corrupt_structures_and_invalid_counts_still_fail(self):
        """已返回但不可解析的结构/值不是平台合法未提供。"""

        payloads = ["", "{", "null", "[]", "{}", '{"props":{"pageProps":[]}}']
        payloads.extend(
            json.dumps({"props": {"pageProps": {"reviewListData": value}}})
            for value in ([], False, "bad")
        )
        payloads.extend(
            json.dumps(
                {
                    "props": {
                        "pageProps": {
                            "reviewListData": {
                                "total_count": value,
                            }
                        }
                    }
                }
            )
            for value in (True, -1, "12", 1.5)
        )
        for payload in payloads:
            with self.subTest(payload=payload), self.assertRaises(ReputationAdapterError) as raised:
                self._http(payload)
            self.assertEqual("REPUTATION_REVIEW_ARTICLE_COUNT_INVALID", raised.exception.code)

    def test_http_wrong_identity_still_fails_before_rate_request(self):
        """页面身份不符时，不因评价篇数可选而放行。"""

        with self.assertRaises(ReputationAdapterError) as raised:
            self._http('{"props":{"pageProps":{}}}', name="另一车型")
        self.assertEqual("REPUTATION_IDENTITY_NAME_MISMATCH", raised.exception.code)
        self.assertEqual(1, self.adapter._http_session.return_value.get.call_count)

    def _browser(self, **overrides):
        """替换页面读写边界，保留_visit的身份、区域、截图和指标提交链。"""

        measurement = {
            "actual_name": "测试车型",
            "score_raw": "3.90",
            "rank_raw": "1",
            "volume_raw": "共1,234人评价",
            "review_article_count_raw": None,
            "review_article_count_invalid": False,
            "reputation_not_available": False,
            "rank_scope": "同级车评分",
            "heading_box": {"x": 40, "y": 40, "width": 200, "height": 50},
            "document_width": 1440,
            "document_height": 1000,
            **overrides,
        }
        page = Mock(url=self.target.platform_url)
        page.goto = AsyncMock(return_value=Mock(status=200))
        page.locator.return_value.first.wait_for = AsyncMock()
        page.wait_for_timeout = AsyncMock()

        async def screenshot(*, path, clip, **_):
            Image.new("RGB", (int(clip["width"]), int(clip["height"])), "white").save(path)

        page.screenshot = AsyncMock(side_effect=screenshot)
        context = Mock(new_page=AsyncMock(return_value=page), close=AsyncMock())
        browser = Mock(new_context=AsyncMock(return_value=context))
        self.adapter._freeze_layout = AsyncMock()
        self.adapter._measure = AsyncMock(return_value=measurement)
        self.adapter._visit_negative_rate = Mock(return_value=("37%", self.rate_url, 214, 128))
        return browser, page, context

    async def test_browser_missing_count_keeps_rate_and_same_visit_evidence(self):
        """三次稳定测量后缺篇数依然采集差评率并保存真正PNG。"""

        browser, page, context = self._browser()
        with tempfile.TemporaryDirectory() as temporary:
            result = await self.adapter._visit(browser, self.target, Path(temporary))
            self.assertIsNone(result.review_article_count_raw)
            self.assertEqual(self.target.platform_url, result.review_article_count_url)
            self.assertEqual("37%", result.negative_rate_raw)
            self.assertEqual(self.rate_url, result.negative_rate_url)
            self.assertEqual("1234", result.volume_raw)
            self.assertEqual(3, len(result.measurements))
            self.assertEqual(
                hashlib.sha256(result.metric_region_path.read_bytes()).hexdigest(),
                result.metric_region_sha256,
            )
            page.screenshot.assert_awaited_once()
            self.adapter._visit_negative_rate.assert_called_once_with(self.target)
        context.close.assert_awaited_once()

    async def test_browser_structure_identity_and_evidence_failures_remain_errors(self):
        """解析错误、错误车型、截图区域缺失/越界继续执行既有失败门禁。"""

        cases = (
            ({"review_article_count_invalid": True}, "REPUTATION_REVIEW_ARTICLE_COUNT_INVALID"),
            ({"actual_name": "另一车型"}, "REPUTATION_IDENTITY_NAME_MISMATCH"),
            ({"heading_box": None}, "REPUTATION_EVIDENCE_REGION_MISSING"),
            ({"document_height": 1}, "REPUTATION_EVIDENCE_REGION_INVALID"),
        )
        for overrides, code in cases:
            with self.subTest(code=code), tempfile.TemporaryDirectory() as temporary:
                browser, page, context = self._browser(**overrides)
                with self.assertRaises(ReputationAdapterError) as raised:
                    await self.adapter._visit(browser, self.target, Path(temporary))
                self.assertEqual(code, raised.exception.code)
                page.screenshot.assert_not_awaited()
                context.close.assert_awaited_once()
