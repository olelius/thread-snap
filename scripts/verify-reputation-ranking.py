"""口碑排名表真实浏览器验收：列对齐、冻结层、不溢出及历史错误按需展示。

只读既有终态批次；默认使用本机项目，也可指向隔离实例。
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:5173")
    parser.add_argument("--run-id")
    parser.add_argument("--output", type=Path, default=Path("artifacts/runtime/reputation-url-fix"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    report = {"checks": [], "page_errors": []}
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
                overflow = page.locator(".ranking-metric, .ranking-error-summary").evaluate_all(
                    "items => items.filter(e => e.scrollWidth > e.clientWidth + 1).map(e => e.textContent)"
                )
                assert not overflow, overflow
                metric_boxes = page.locator(".ranking-metric").evaluate_all(
                    'items => items.map(e => {const a=e.getBoundingClientRect(), b=e.closest("td").getBoundingClientRect(); return {l:a.left-b.left,r:a.right-b.right}})'
                )
                assert all(item["l"] >= -1 and item["r"] <= 1 for item in metric_boxes), (
                    metric_boxes
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
                page.close()
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
