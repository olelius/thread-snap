"""口碑浏览器稳定采样的轻量合同测试。"""

from __future__ import annotations

import unittest
from itertools import count
from time import monotonic

from threadsnap.reputation_adapter import ReputationAdapterError
from threadsnap.reputation_browser import attempt_timeout, settle_measure


def _sample(name: str = "测试车型", *, x: float = 10.0, score: str | None = "4.2") -> dict:
    return {
        "actual_name": name,
        "score": score,
        "rank": "1",
        "volume": "12",
        "rect": {"x": x, "y": 20.0, "width": 100.0, "height": 40.0},
        "document_width": 1440,
        "document_height": 900,
    }


class ReputationLayoutSettleTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_node_is_resampled_until_late_stable_window(self) -> None:
        values = iter([None, None, _sample(), _sample(), _sample()])

        async def measure():
            return next(values)

        result, samples = await settle_measure(measure, interval_seconds=0.001)
        self.assertEqual("测试车型", result["actual_name"])
        self.assertEqual(5, len(samples))

    async def test_one_pixel_edge_jitter_returns_outward_union(self) -> None:
        values = iter([_sample(x=10.0), _sample(x=10.6), _sample(x=10.2)])

        async def measure():
            return next(values)

        result, _ = await settle_measure(measure, interval_seconds=0.001)
        self.assertEqual(10.0, result["rect"]["x"])
        self.assertEqual(101.0, result["rect"]["width"])

    async def test_failures_distinguish_drift_content_and_deadline(self) -> None:
        for drifting in (True, False):
            with self.subTest(drifting=drifting):
                sequence = count()

                async def measure():
                    index = next(sequence)
                    # 每次只移 0.6px，但三次累计 1.2px，不能误当稳定。
                    return _sample(x=10 + index * 0.6) if drifting else _sample(score=str(index))

                with self.assertRaises(ReputationAdapterError) as raised:
                    await settle_measure(measure, interval_seconds=0.001, window_seconds=0.4)
                self.assertEqual(drifting, raised.exception.metrics_stable)
                self.assertEqual(drifting, raised.exception.layout_only)
                self.assertLessEqual(len(raised.exception.measurements), 13)

        async def no_geometry():
            return {**_sample(), "rect": None}

        result, _ = await settle_measure(no_geometry, geometry_required=False, interval_seconds=0.001)
        self.assertEqual("4.2", result["score"])
        started = monotonic()
        with self.assertRaises(ReputationAdapterError):
            async with attempt_timeout(0.02):
                await settle_measure(no_geometry, window_seconds=3.0)
        self.assertLess(monotonic() - started, 0.2)


if __name__ == "__main__":
    unittest.main()
