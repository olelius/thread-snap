from __future__ import annotations

import unittest
from decimal import Decimal

from threadsnap.migrations.versions.a6c9e2f4b701_review_article_count import _scrub
from threadsnap.migrations.versions.b7d2f4a6c803_normalize_reputation_metric_text import (
    _normalize_metrics,
)
from threadsnap.reputation import _metric


class ReputationMetricMigrationTests(unittest.TestCase):
    def test_new_negative_delta_is_persisted_as_text(self) -> None:
        metric = _metric(Decimal("1223"), Decimal("1224"))

        self.assertEqual("-1", metric["delta"])
        self.assertIsInstance(metric["delta"], str)

    def test_retired_metric_scrub_preserves_string_leaf_types(self) -> None:
        source = {
            "score": {"raw": "4.00", "value": "4.00", "delta": "-1"},
            "circle_content": {"raw": "2093"},
            "nested": [{"circle_content": "remove", "value": "1223"}],
        }

        self.assertEqual(
            {
                "score": {"raw": "4.00", "value": "4.00", "delta": "-1"},
                "nested": [{"value": "1223"}],
            },
            _scrub(source),
        )

    def test_normalize_metrics_repairs_only_metric_text_fields(self) -> None:
        metrics = {
            "volume": {
                "raw": 1223,
                "value": 1223,
                "baseline_raw": 1224,
                "baseline_value": 1224,
                "delta": -1,
                "direction": "down",
                "positive_count": 10,
            }
        }

        normalized, changed = _normalize_metrics(metrics)

        self.assertTrue(changed)
        self.assertEqual("1223", normalized["volume"]["raw"])
        self.assertEqual("-1", normalized["volume"]["delta"])
        self.assertEqual(10, normalized["volume"]["positive_count"])


if __name__ == "__main__":
    unittest.main()
