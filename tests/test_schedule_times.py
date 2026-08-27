"""循环计划触发序列与请求合同测试。"""

from __future__ import annotations

import unittest

from pydantic import ValidationError

from threadsnap.schedule_times import recurring_trigger_times
from threadsnap.schemas import RecurringScheduleNodeDraft


class RecurringScheduleTimesTest(unittest.TestCase):
    """验证开始、结束边界和同日窗口约束。"""

    def test_start_is_included_and_end_requires_exact_alignment(self) -> None:
        self.assertEqual(
            ["09:00:00", "09:05:00", "09:10:00", "09:15:00"],
            recurring_trigger_times("09:00:00", "09:15:00", 5),
        )
        self.assertEqual(
            ["09:00:00", "09:07:00", "09:14:00"],
            recurring_trigger_times("09:00:00", "09:15:00", 7),
        )

    def test_recurring_draft_rejects_cross_midnight_or_empty_window(self) -> None:
        common = {
            "id": "recurring-node-0001",
            "weekdays": [0],
            "interval_minutes": 5,
            "enabled": True,
            "rule_ids": ["rule-0001"],
        }
        for start_time, end_time in (("23:00:00", "01:00:00"), ("09:00:00", "09:00:00")):
            with self.subTest(start_time=start_time, end_time=end_time):
                with self.assertRaises(ValidationError):
                    RecurringScheduleNodeDraft(
                        **common,
                        start_time=start_time,
                        end_time=end_time,
                    )


if __name__ == "__main__":
    unittest.main()
