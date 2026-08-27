"""计划节点实际触发时刻的统一计算。"""

from __future__ import annotations


def time_to_seconds(value: str) -> int:
    """把规范化的 ``HH:mm:ss`` 转换为自然日内秒数。"""

    hour, minute, second = (int(part) for part in value.split(":"))
    return hour * 3600 + minute * 60 + second


def seconds_to_time(value: int) -> str:
    """把自然日内秒数转换为规范化的 ``HH:mm:ss``。"""

    hour, remainder = divmod(value, 3600)
    minute, second = divmod(remainder, 60)
    return f"{hour:02d}:{minute:02d}:{second:02d}"


def recurring_trigger_times(
    start_time: str, end_time: str, interval_minutes: int
) -> list[str]:
    """展开同日循环窗口；开始必含，结束仅在间隔序列命中时包含。"""

    start = time_to_seconds(start_time)
    end = time_to_seconds(end_time)
    step = interval_minutes * 60
    if start >= end or step <= 0:
        return []
    return [seconds_to_time(value) for value in range(start, end + 1, step)]


def schedule_node_trigger_times(
    node_type: str,
    time_of_day: str,
    end_time_of_day: str | None = None,
    interval_minutes: int | None = None,
) -> list[str]:
    """按节点类型返回一天内的全部实际触发时刻。"""

    if node_type == "weekly":
        return [time_of_day]
    if node_type == "recurring" and end_time_of_day and interval_minutes:
        return recurring_trigger_times(time_of_day, end_time_of_day, interval_minutes)
    return []
