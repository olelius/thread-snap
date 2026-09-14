"""汽车之家身份仅比较车系ID，名称为展示字段；仅覆盖本次两条分支。"""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from threadsnap.reputation_adapter import ReputationAdapterError, ReputationMappingTarget
from threadsnap.reputation_autohome import AutohomeReputationAdapter


class AutohomeIdentityTests(unittest.IsolatedAsyncioTestCase):
    async def visit(self, name, actual_id, final_id="7711"):
        target = ReputationMappingTarget(
            "v1", "7711", "https://k.autohome.com.cn/7711/", name, "a" * 64
        )
        response = SimpleNamespace(status=200)
        page = SimpleNamespace(
            url=f"https://k.autohome.com.cn/{final_id}/",
            set_default_timeout=lambda _: None,
            goto=AsyncMock(return_value=response),
            wait_for_selector=AsyncMock(),
        )
        context = SimpleNamespace(
            new_page=AsyncMock(return_value=page),
            close=AsyncMock(),
            request=SimpleNamespace(
                get=AsyncMock(
                    return_value=SimpleNamespace(
                        ok=True,
                        json=AsyncMock(
                            return_value={
                                "result": {
                                    "seriesid": actual_id,
                                    "seriesname": "捷途山海L7",
                                    "average": "4.12",
                                }
                            }
                        ),
                    )
                )
            ),
        )
        browser = SimpleNamespace(new_context=AsyncMock(return_value=context))
        measurement = {
            "actual_name": "奇瑞汽车-捷途山海L7",
            "score": "4.12",
            "rect": {"x": 0, "y": 0, "width": 200, "height": 100},
        }
        with (
            tempfile.TemporaryDirectory() as root,
            patch(
                "threadsnap.reputation_autohome.stable_measure",
                AsyncMock(return_value=(measurement, [measurement])),
            ),
            patch(
                "threadsnap.reputation_autohome.capture_region",
                AsyncMock(return_value=(200, 100, "b" * 64)),
            ),
        ):
            return await AutohomeReputationAdapter(None)._visit(browser, target, Path(root))

    async def test_display_name_never_blocks_matching_id(self):
        for name in ("奇瑞汽车-捷途山海L7", "捷途山海L7", "项目组内显示名称"):
            with self.subTest(name=name):
                result = await self.visit(name, 7711)
                self.assertEqual("4.12", result.score_raw)
                self.assertEqual("捷途山海L7", result.actual_name)
                self.assertEqual(7711, result.measurements[0]["api_seriesid"])

    async def test_same_series_stopselling_page_is_supported(self):
        result = await self.visit("厂家-展示名", 7711, "7711/stopselling")
        self.assertEqual("https://k.autohome.com.cn/7711/stopselling", result.final_url)
        with self.assertRaises(ReputationAdapterError):
            await self.visit("厂家-展示名", 7397, "7397/stopselling")

    async def test_wrong_or_missing_id_and_wrong_url_are_still_rejected(self):
        for actual_id, final_id in ((7397, "7711"), (None, "7711"), (7711, "7397")):
            with self.subTest(actual_id=actual_id, final_id=final_id):
                with self.assertRaises(ReputationAdapterError):
                    await self.visit("捷途山海L7", actual_id, final_id)
