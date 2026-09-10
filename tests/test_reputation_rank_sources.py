"""汽车之家页面评分榜排名来源的确定性合同测试。"""

import unittest

from threadsnap.reputation_autohome import comparison_rank


class AutohomeComparisonRankTests(unittest.TestCase):
    def test_uses_target_id_and_original_order_instead_of_level_rank(self) -> None:
        payload = {
            "average": "4.56",
            "levelrank": 10,
            "cmpSeriesTitle": "热门对比车系评分排行",
            "cmpSeriesScore": [
                {"seriesId": 7072, "score": "4.56"},
                {"seriesId": 6004, "score": "4.52"},
            ],
        }
        rank, scope = comparison_rank(payload, "7072")
        self.assertEqual("1", rank)
        self.assertTrue(scope.endswith(":热门对比车系评分排行"))

    def test_keeps_nonfirst_and_same_score_platform_order(self) -> None:
        payload = {
            "average": "4.48",
            "cmpSeriesTitle": "热门对比车系评分排行",
            "cmpSeriesScore": [
                {"seriesId": 1, "score": "4.55"},
                {"seriesId": 2, "score": "4.55"},
                {"seriesId": 3, "score": "4.51"},
                {"seriesId": 6651, "score": "4.48"},
            ],
        }
        self.assertEqual("4", comparison_rank(payload, "6651")[0])

    def test_unscored_absent_duplicate_or_wrong_board_is_empty(self) -> None:
        for payload in (
            {"average": "0.00", "cmpSeriesTitle": "热门对比车系评分排行", "cmpSeriesScore": [{"seriesId": 1}]},
            {"average": "4.5", "cmpSeriesTitle": "热门对比车系评分排行", "cmpSeriesScore": [{"seriesId": 2}]},
            {"average": "4.5", "cmpSeriesTitle": "热门对比车系评分排行", "cmpSeriesScore": [{"seriesId": 1}, {"seriesId": 1}]},
            {"average": "4.5", "cmpSeriesTitle": "质量排行", "cmpSeriesScore": [{"seriesId": 1}]},
        ):
            self.assertIsNone(comparison_rank(payload, "1")[0])


if __name__ == "__main__":
    unittest.main()
