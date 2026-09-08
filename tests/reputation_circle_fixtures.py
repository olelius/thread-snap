"""圈子计数测试的脱敏结构夹具；不是平台原始HTML或真实采集记录。"""

from __future__ import annotations

import json

from threadsnap.reputation_adapter import ReputationMappingTarget
from threadsnap.reputation_dongchedi import DongchediReputationAdapter


def circle_html(series_id: str, name: str, count: int | None) -> bytes:
    """复现两份已核对样本共有的SSR结构，不含用户帖子或Cookie。"""

    props = {
        "series_id": series_id,
        "cheyouHead": {"series_id": int(series_id), "series_name": name},
        "cheyouList": {"total_count": count},
    }
    label = "" if count is None else f"共{count}条内容"
    return (
        f'<html><head><meta charset="utf-8"></head><body><h1>{name}车友圈</h1><div>{label}</div>'
        f'<script id="__NEXT_DATA__">{json.dumps({"props": {"pageProps": props}}, ensure_ascii=False)}</script>'
        "</body></html>"
    ).encode()


def circle_result_fields(target: ReputationMappingTarget, count: int | None = 500) -> dict:
    """确定性适配器也从真实形状解析路径形成可验证的同次采集证明。"""

    url = f"https://www.dongchedi.com/community/{target.platform_vehicle_id}/dongtai-release"
    raw, proof = DongchediReputationAdapter._parse_circle_content(
        target,
        url,
        circle_html(target.platform_vehicle_id, target.platform_display_name, count),
    )
    return {
        "circle_content_count_raw": raw,
        "circle_content_count_url": url,
        "circle_content_count_measurement": proof,
    }
