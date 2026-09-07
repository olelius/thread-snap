"""口碑排名表真实浏览器验收：固定卡片间距、无异常脚注、列对齐与冻结层。

只读既有终态批次；默认使用本机项目，也可指向隔离实例。
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def assert_metric_layout(page, scale=1):
    """测量全部实际卡片而非仅检查溢出；缩放时换算回 CSS 像素。"""
    geometry = page.locator(".ranking-metric").evaluate_all("""items => {
      const boxes=items.map(e => {
        const a=e.getBoundingClientRect(), td=e.closest('td'), b=td.getBoundingClientRect();
        const next=td.nextElementSibling?.querySelector('.ranking-metric');
        return {width:a.width, cellWidth:b.width, height:a.height,
          left:a.left-b.left, right:b.right-a.right,
          gap:next ? next.getBoundingClientRect().left-a.right : null};
      });
      const overflow=items.flatMap(e => [e, ...e.querySelectorAll('span')])
        .filter(e => e.scrollWidth > e.clientWidth+1 || e.scrollHeight > e.clientHeight+1)
        .map(e => e.textContent);
      return {boxes, overflow};
    }""")
    boxes = geometry["boxes"]
    assert boxes, "实际指标卡片分母为0"
    assert not geometry["overflow"], geometry["overflow"]
    assert all(abs(box["width"] / scale - 136) <= 1 for box in boxes), boxes
    assert all(abs(box["cellWidth"] / scale - 160) <= 1 for box in boxes), boxes
    assert all(box["height"] / scale >= 55 for box in boxes), boxes
    assert all(min(box["left"], box["right"]) / scale >= 11 for box in boxes), boxes
    gaps = [box["gap"] / scale for box in boxes if box["gap"] is not None]
    assert gaps and min(gaps) >= 23.5, gaps
    # 所有状态单元格仅有状态行，防止把旧说明替换成另一段小字。
    assert page.locator(".ranking-error-summary").count() == 0
    extras = page.locator('[data-ranking-cell$="-state"]').evaluate_all("""items =>
      items.filter(e => e.children.length !== 1 || !e.firstElementChild.matches('.ranking-state-line'))
        .map(e => e.textContent)
    """)
    assert not extras, extras
    return {
        "tiles": len(boxes),
        "adjacent_pairs": len(gaps),
        "min_gap": min(gaps),
        "widths": sorted({round(box["width"] / scale, 2) for box in boxes}),
        "status_cells": page.locator('[data-ranking-cell$="-state"]').count(),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:5173")
    parser.add_argument("--run-id")
    parser.add_argument("--output", type=Path, default=Path("artifacts/runtime/reputation-url-fix"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    report = {"checks": [], "page_errors": [], "base_url": args.base_url}
    base = args.base_url.rstrip("/")

    def record(name, **details):
        report["checks"].append({"name": name, "status": "passed", **details})
        print("PASS", name, flush=True)

    def digest(value):
        return hashlib.sha256(
            json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        request = context.request
        runs = request.get(base + "/api/v1/reputation/runs?limit=20").json()["items"]
        run_id = args.run_id or next(
            row["id"]
            for row in runs
            if row["planned_count"] == 81 and row["source_type"] == "scheduled"
        )
        endpoint = base + f"/api/v1/reputation/runs/{run_id}"
        original = request.get(endpoint).json()
        original_hash = digest(original)
        report.update(run_id=run_id, number=original["number"])
        try:
            modes = request.get(base + "/api/v1/reputation/capabilities").json()[
                "reputation_platforms"
            ]
            assert (
                next(row for row in modes if row["code"] == "yiche")["evidence_mode"] == "url_only"
            )
            record("url-only-mode-published")
            for width, height, theme in [
                (2560, 1293, "light"),
                (1440, 1000, "light"),
                (1440, 1000, "dark"),
                (1024, 900, "light"),
            ]:
                page = context.new_page()
                page.set_viewport_size({"width": width, "height": height})
                page.emulate_media(color_scheme=theme)
                page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
                page.goto(base + f"/reputation/runs/{run_id}?view=ranking")
                viewport = page.locator("[data-ranking-viewport]")
                expect(page.locator('[data-ranking-cell="yiche-state"]').first).to_be_attached()
                expect(page.get_by_role("note")).to_contain_text("URL 模式")
                page.wait_for_timeout(500)
                assert viewport.locator("table").count() == 1
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                record(
                    f"fixed-tiles-no-error-caption-{width}-{theme}", **assert_metric_layout(page)
                )

                snapshots = []
                for fraction in (0, 0.45, 1):
                    viewport.evaluate(
                        "(e, f) => {e.scrollLeft=(e.scrollWidth-e.clientWidth)*f; e.scrollTop=f ? 470 : 0}",
                        fraction,
                    )
                    page.wait_for_timeout(100)
                    geometry = viewport.evaluate("""e => {
                      const box=e.getBoundingClientRect();
                      const headers=[...e.querySelectorAll('th[data-ranking-column]')];
                      const deltas=headers.map(th => {const td=e.querySelector('td[data-ranking-cell="'+th.dataset.rankingColumn+'"]'); return Math.abs(th.getBoundingClientRect().left-td.getBoundingClientRect().left)});
                      const head=e.querySelector('thead').getBoundingClientRect();
                      const frozen=e.querySelector('tbody .ranking-role').getBoundingClientRect();
                      const sample=document.elementFromPoint(box.left+270, box.top+15);
                      return {scrollLeft:e.scrollLeft, deltas, headOffset:head.top-box.top, frozenOffset:frozen.left-box.left, headerOnTop:!!sample?.closest('thead')};
                    }""")
                    assert max(geometry["deltas"]) <= 1, geometry
                    assert abs(geometry["headOffset"]) <= 2, geometry
                    assert abs(geometry["frozenOffset"]) <= 2, geometry
                    assert geometry["headerOnTop"], geometry
                    snapshots.append(geometry)
                    page.screenshot(
                        path=str(args.output / f"ranking-{width}-{theme}-{fraction}.png"),
                        animations="disabled",
                    )
                record(f"alignment-overflow-sticky-{width}-{theme}", positions=snapshots)

                native = next(
                    (
                        row
                        for row in original["results"]
                        if (row.get("error_code") or "").startswith("REPUTATION_NATIVE_")
                    ),
                    None,
                )
                if native:
                    assert native["error_message"] not in page.locator("body").inner_text()
                    button = page.get_by_role(
                        "button",
                        name=f"查看{native['vehicle_name']}{native['platform_name']}失败原因",
                        exact=True,
                    )
                    button.click()
                    expect(page.get_by_role("dialog")).to_contain_text(native["error_message"])
                    page.keyboard.press("Escape")
                    expect(page.get_by_role("dialog")).to_have_count(0)
                    record(f"historical-native-error-on-demand-{width}-{theme}")
                # 图中另一处为懂车帝普通异常，同样没有小字且原文仍可按需查看。
                ordinary = next(
                    row
                    for row in original["results"]
                    if row.get("error_message")
                    and not (row.get("error_code") or "").startswith("REPUTATION_NATIVE_")
                )
                assert ordinary["error_message"] not in page.locator("body").inner_text()
                page.get_by_role(
                    "button",
                    name=f"查看{ordinary['vehicle_name']}{ordinary['platform_name']}失败原因",
                    exact=True,
                ).click()
                expect(page.get_by_role("dialog")).to_contain_text(ordinary["error_message"])
                page.keyboard.press("Escape")
                expect(page.get_by_role("dialog")).to_have_count(0)
                record(f"ordinary-error-on-demand-{width}-{theme}")
                if width == 2560:
                    # 放大布局/文字后仍有真实卡片间隔，不以裁切文字通过断言。
                    for zoom in (1.25, 2):
                        page.evaluate("z => document.documentElement.style.zoom=String(z)", zoom)
                        page.wait_for_timeout(300)
                        record(f"zoomed-tiles-{zoom}", **assert_metric_layout(page, zoom))
                    page.evaluate("document.documentElement.style.zoom=''")
                page.close()
            # 单平台URL模式不应在汇报卡中被误标为“缺图”或“证据已生成”。
            import copy

            fixture = copy.deepcopy(original)
            fixture.update(
                id="url-only-fixture",
                number="URL模式验收",
                source_type="synthetic",
                platform_codes=["yiche"],
                planned_count=27,
                completed_count=27,
                failed_count=0,
                required_evidence_count=0,
                complete_evidence_count=0,
                linked_complete_evidence_count=0,
                resolved_count=27,
                unresolved_count=0,
                linked_status="success",
                status="success",
                report_status="success",
                report_text="URL模式：本批次未要求截图。",
                downloads={},
                retry_runs=[],
            )
            fixture["results"] = [
                dict(
                    item,
                    status="success",
                    evidence_required=False,
                    evidence=None,
                    error_code=None,
                    error_message=None,
                )
                for item in original["results"]
                if item["platform_code"] == "yiche"
            ]
            page = context.new_page()
            page.route(
                "**/api/v1/reputation/runs/url-only-fixture*",
                lambda route: route.fulfill(
                    status=200, content_type="application/json", body=json.dumps(fixture)
                ),
            )
            page.goto(base + "/reputation/runs/url-only-fixture?view=report")
            row = page.get_by_text("页面证据 ZIP", exact=True).locator("..")
            expect(row).to_contain_text("未要求截图")
            page.screenshot(path=str(args.output / "url-only-report-fixture.png"))
            page.close()
            record("url-only-report-not-marked-as-missing", source="browser fixture")

            current = request.get(endpoint).json()
            assert digest(current) == original_hash, "历史批次响应发生变化"
            record("historical-snapshot-unchanged", sha256=original_hash)
            assert not report["page_errors"], report["page_errors"]
            report["status"] = "passed"
        except Exception as error:
            report["status"] = "failed"
            report["error"] = str(error)
            if "page" in locals() and not page.is_closed():
                page.screenshot(path=str(args.output / "failure.png"))
            raise
        finally:
            (args.output / "ranking-verification.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            browser.close()


if __name__ == "__main__":
    main()
