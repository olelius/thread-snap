"""将同一批次冻结结果呈现为两种重点车型汇报，不查询平台或改写历史。"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Sequence


def _decimal(value: Any) -> Decimal | None:
    """接受冻结数字文本，拒绝空值、布尔及非有限数。"""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
        return number if number.is_finite() else None
    except InvalidOperation:
        return None


def _value(metric: dict[str, Any] | None) -> str:
    if metric is None:
        return "未采集"
    raw = metric.get("raw")
    return "—" if raw is None or raw == "" else str(raw)


def _change(metric: dict[str, Any] | None) -> str:
    """增减描述使用数学差值；排名与差评率不按好坏倒置正负号。"""
    if metric is None:
        return "未采集"
    if metric.get("comparison_status") == "not_comparable":
        return "口径变化，不作比较"
    delta = _decimal(metric.get("delta"))
    if (
        metric.get("comparison_status") != "comparable"
        or metric.get("raw") in (None, "")
        or delta is None
    ):
        return "暂无前日可比数据"
    if delta == 0:
        return "按显示值持平(0)" if metric.get("quantity_kind") == "rounded" else "持平(0)"
    magnitude = format(abs(delta), "f")
    if "." in magnitude:
        magnitude = magnitude.rstrip("0").rstrip(".")
    change = f"增加(+{magnitude})" if delta > 0 else f"减少(-{magnitude})"
    return f"按显示值{change}" if metric.get("quantity_kind") == "rounded" else change


def _changed(metric: dict[str, Any] | None) -> bool:
    if not metric or metric.get("comparison_status") != "comparable":
        return False
    delta = _decimal(metric.get("delta"))
    return metric.get("raw") not in (None, "") and delta is not None and delta != 0


def render_report_templates(run: Any, results: Sequence[Any]) -> list[dict[str, str]]:
    """按冻结顺序生成两模板；results必须是原批次自身结果，不含晚到补跑。"""
    focus = [row for row in results if row.role == "focus"]
    vehicles = list({row.vehicle_id: row for row in focus}.values())
    by_target = {(row.vehicle_id, row.platform_code): row for row in focus}
    incomplete = sum(row.status != "success" for row in focus)
    warning = (
        [f"【数据不完整：重点车型有{incomplete}个执行项未完整成功。】", ""] if incomplete else []
    )
    details = list(warning)
    fields = (
        ("懂车帝车友圈露出数", "dongchedi", "circle_content_count"),
        ("汽车之家论坛数", "autohome", "circle_content_count"),
        ("懂车帝口碑分", "dongchedi", "score"),
        ("汽车之家口碑分", "autohome", "score"),
        ("懂车帝口碑帖数量", "dongchedi", "review_article_count"),
        ("汽车之家口碑帖数量", "autohome", "review_article_count"),
        ("懂车帝差评率", "dongchedi", "negative_rate"),
    )
    for vehicle in vehicles:
        details.append(f"车型：{vehicle.vehicle_name}")
        for number, (label, platform, key) in enumerate(fields, 1):
            row = by_target.get((vehicle.vehicle_id, platform))
            metric = row.metrics.get(key) if row and key else None
            details.extend([f"{number}、{label}：{_value(metric)}", f"-{_change(metric)}"])
        details.append("")
    if not vehicles:
        details.append("本批次无重点车型。")

    changes = [
        *warning,
        "各位老师，今日本竞品口碑排名表已更新，",
        f"{run.planned_date}本品口碑分及排名变动如下：",
    ]
    for platform, label in (("dongchedi", "懂车帝"), ("autohome", "汽车之家"), ("yiche", "易车")):
        if platform not in run.platform_codes:
            continue
        changes.extend(["", label])
        rows = [row for row in focus if row.platform_code == platform]
        keys = ("score", "rank", "negative_rate") if platform == "dongchedi" else ("score", "rank")
        changed = [row for row in rows if any(_changed(row.metrics.get(key)) for key in keys)]
        for number, row in enumerate(changed, 1):
            score, rank = row.metrics.get("score"), row.metrics.get("rank")
            line = (
                f"{number}、{row.vehicle_name}&口碑分{_value(score)}，{_change(score)}，"
                f"排名第{_value(rank)}，{_change(rank)}"
            )
            if platform == "dongchedi":
                line += f"，差评率{_value(row.metrics.get('negative_rate'))}"
            changes.append(line)
        if not changed:
            comparable = any(
                row.metrics.get(key, {}).get("comparison_status") == "comparable"
                and row.metrics.get(key, {}).get("raw") not in (None, "")
                for row in rows
                for key in keys
            )
            changes.append(
                "本平台无重点车型。"
                if not rows
                else "今日重点车型无可确认变动。"
                if comparable
                else "暂无前日可比数据，未列出车型。"
            )
    return [
        {
            "id": "vehicle_detail",
            "label": "模板一：车型明细",
            "text": "\n".join(details).rstrip() + "\n",
        },
        {
            "id": "daily_changes",
            "label": "模板二：每日变动",
            "text": "\n".join(changes).rstrip() + "\n",
        },
    ]
