"""懂车帝圈子可见精确计数的纯文本解析，不访问网络或帖子。"""

from __future__ import annotations

import re
from typing import Any


def circle_count_visible_text(document: Any) -> str:
    """只读取页面自身的非隐藏文本，排除脚本与帖子卡片中的引用计数。"""

    return " ".join(
        document.xpath(
            "//body//text()[not(ancestor::script) and not(ancestor::style)"
            " and not(ancestor::noscript) and not(ancestor::*[@hidden or @aria-hidden='true'])"
            " and not(ancestor::*[contains(concat(' ',normalize-space(@class),' '),' community-card ')])]"
        )
    )


def parse_circle_content_count(text: str) -> tuple[int | None, str | None]:
    """读取“共 N 条内容”；缺文案返回空，非法或相互矛盾的计数报错。"""

    labels = [value.strip() for value in re.findall(r"共([^<>共]*?)条内容", text)]
    if not labels:
        return None, None
    if any(re.fullmatch(r"[0-9]+", value) is None for value in labels):
        raise ValueError("圈子内容数不是精确非负整数")
    counts = {int(value) for value in labels}
    if len(counts) != 1:
        raise ValueError("圈子页面出现相互矛盾的内容总数")
    match = re.search(r"共\s*[0-9]+\s*条内容", text)
    return counts.pop(), match.group(0) if match else None
