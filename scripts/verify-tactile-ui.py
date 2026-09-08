"""对已构建的触感前端执行浏览器验收；建议指向关闭 Worker 的数据库副本。

默认只读。--isolated-writes 显式允许在隔离后端验证配置保存及创建排队批次。
认证错误/空列表等边界只在浏览器拦截响应，不启动平台浏览器或访问平台。
输出 JSON、PNG 保存在指定 runtime 目录，测试数据不进入 Git。
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:5176")
    parser.add_argument("--output", type=Path, default=Path("artifacts/runtime/tactile-home"))
    parser.add_argument("--isolated-writes", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    base = args.base_url.rstrip("/")
    report: dict = {
        "base_url": base,
        "isolated_writes": args.isolated_writes,
        "checks": [],
        "page_errors": [],
    }

    def passed(name: str, **evidence) -> None:
        report["checks"].append({"name": name, "status": "passed", **evidence})
        print(f"PASS {name}", flush=True)

    def shot(page, name: str) -> None:
        page.wait_for_timeout(400)
        page.screenshot(path=str(args.output / f"{name}.png"), animations="disabled")

    def no_overflow(page) -> None:
        size = page.evaluate(
            "({viewport: innerWidth, body: document.body.scrollWidth, root: document.documentElement.scrollWidth})"
        )
        assert max(size["body"], size["root"]) <= size["viewport"] + 1, size

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1440, "height": 1050}, color_scheme="light"
        )
        page = context.new_page()
        context.on(
            "page", lambda new: new.on("pageerror", lambda e: report["page_errors"].append(str(e)))
        )
        page.on("pageerror", lambda e: report["page_errors"].append(str(e)))
        try:

            def api(path: str):
                response = context.request.get(base + "/api/v1" + path)
                assert response.ok, (path, response.status)
                return response.json()

            runs = api("/runs?offset=0&limit=50&trigger_types=manual&trigger_types=scheduled")
            assert len(runs["items"]) >= 2, "验收副本至少需要两个批次，以覆盖批次选择和详情。"
            first = runs["items"][0]
            completed = api(
                "/runs?offset=0&limit=50&status=success&trigger_types=manual&trigger_types=scheduled"
            )["items"]
            second = completed[1]
            report["data"] = {"list_count": len(runs["items"]), "total": runs["total"]}
            dashboard = api("/dashboard")
            report["dashboard"] = {
                c["key"]: {k: c[k] for k in ("total", "today", "active", "attention")}
                for c in dashboard["categories"]
            }
            page.goto(base + "/")
            expect(page.locator("html")).to_have_attribute("data-ui", "tactile")
            for category in dashboard["categories"]:
                expect(
                    page.locator(f'[data-home-total="{category["key"]}"] [data-count-value]')
                ).to_have_text(str(category["total"]))
            assert page.url.rstrip("/") == base
            no_overflow(page)
            shot(page, "default-light")
            passed(
                "default-home-global-aggregation",
                global_count=dashboard["categories"][0]["total"],
                list_page_count=len(runs["items"]),
            )

            for group in dashboard["categories"]:
                page.get_by_role("button", name=group["label"], exact=True).click()
                expect(page.locator(".home-batch")).to_have_count(len(group["recent"]))
                if group["recent"]:
                    expect(page.locator(".home-selected-number")).to_have_text(
                        group["recent"][0]["number"]
                    )
                else:
                    expect(page.get_by_text("暂无该类批次", exact=True)).to_be_visible()
            page.get_by_role("button", name="提取批次", exact=True).click()
            passed("home-three-categories-and-empty-state")

            choice = dashboard["categories"][0]["recent"][1]
            page.locator(".home-batch").nth(1).click()
            expect(page.locator(".home-selected-number")).to_have_text(choice["number"])
            assert page.url.rstrip("/") == base
            card = page.locator(".home-batch").nth(1)
            box = card.bounding_box()
            page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            before = card.evaluate("e => getComputedStyle(e).transform")
            page.mouse.down()
            page.wait_for_timeout(230)
            pressed = card.evaluate("e => getComputedStyle(e).transform")
            page.mouse.up()
            assert before != pressed, (before, pressed)
            page.locator(".home-open-detail").click()
            page.wait_for_url(f"**/runs/{choice['id']}*")
            passed("home-selection-press-and-detail-link")
            page.goto(base + f"/runs/{second['id']}")
            page.locator("[data-post-detail-trigger=true]").first.wait_for()
            page.locator("[data-post-detail-trigger=true]").first.click()
            expect(page.get_by_role("dialog")).to_be_visible()
            shot(page, "post-detail-sheet")
            page.get_by_role("dialog").get_by_role("button", name="关闭", exact=True).click()
            expect(page.get_by_role("dialog")).to_have_count(0)
            assert "/runs/" in page.url
            passed("batch-detail-post-sheet-and-close")

            page.goto(base + "/")
            before_submit = api("/dashboard")["categories"][0]["total"]
            page.get_by_role("button", name="新建提取", exact=True).click()
            expect(page.get_by_role("dialog")).to_be_visible()
            expect(page.get_by_role("button", name="提交提取", exact=True)).to_be_disabled()
            page.get_by_role("radio", name=re.compile("URL 清单")).click()
            page.get_by_label("帖子 URL 清单").fill("https://www.dongchedi.com/ugc/article/1001")
            shot(page, "new-extraction-sheet")
            if args.isolated_writes:
                page.get_by_role("dialog").get_by_role("switch").first.click()
                with page.expect_response(
                    lambda r: "/runs/manual" in r.url and r.request.method == "POST"
                ) as saved:
                    page.get_by_role("button", name="提交提取", exact=True).click()
                assert saved.value.ok, saved.value.text()
                result = saved.value.json()
                assert result["status"] == "queued"
                expect(
                    page.locator('[data-home-total="extraction"] [data-count-value]')
                ).to_have_text(str(before_submit + 1), timeout=8000)
                passed(
                    "manual-submit-isolated-api", created_id=result["id"], state=result["status"]
                )
            else:
                page.get_by_role("button", name="关闭并放弃当前输入").click()
            passed("new-extraction-input-and-validation")

            page.goto(base + "/runs")
            field = page.get_by_role("textbox", name="搜索批次编号")
            field.fill(first["number"])
            page.wait_for_url(re.compile("number="))
            expect(page.locator('[data-list-footer="runs"]')).to_contain_text("共 1 个批次")
            page.reload()
            expect(field).to_have_value(first["number"])
            expect(page.locator('[data-list-footer="runs"]')).to_contain_text("共 1 个批次")
            passed("search-url-reload-and-api-filter")

            page.goto(base + "/runs")
            page.locator('[data-list-viewport="runs"] tbody tr').first.wait_for()
            page.keyboard.press("Control+k")
            command = page.locator("input[role=combobox]")
            expect(command).to_be_focused()
            command.fill("口碑巡检")
            command.press("ArrowDown")
            command.press("Enter")
            page.wait_for_url("**/reputation*")
            expect(page.get_by_role("tab", name="巡检批次", exact=True)).to_be_visible()
            shot(page, "reputation-list")
            passed("command-keyboard-and-reputation-route")

            reputation = api("/reputation/runs?offset=0&limit=1")["items"]
            assert reputation, "验收副本需要至少一个巡检批次。"
            for view, label in [
                ("ranking", "排名数据"),
                ("evidence", "页面证据"),
                ("report", "汇报结果"),
            ]:
                page.goto(base + f"/reputation/runs/{reputation[0]['id']}?view={view}")
                expect(page.get_by_role("tab", name=label, exact=True)).to_have_attribute(
                    "data-state", "active"
                )
                shot(page, f"reputation-{view}")
            passed("reputation-ranking-evidence-report-deeplinks")

            tabs = [
                ("rules", "自动提取规则"),
                ("schedule", "每周计划"),
                ("recurring", "循环计划"),
                ("platforms", "平台配置"),
                ("circles", "来源与圈子"),
                ("history", "手动圈子历史"),
                ("templates", "导出模板"),
                ("sentiment", "AI 舆情"),
            ]
            for key, label in tabs:
                page.goto(base + "/config?tab=" + key)
                expect(page.get_by_role("tab", name=label, exact=True)).to_have_attribute(
                    "data-state", "active"
                )
                assert page.locator("text=Something went wrong").count() == 0
            passed("all-eight-config-tabs", count=8)
            page.goto(base + "/config?tab=platforms")
            expect(page.get_by_role("tab", name="平台配置", exact=True)).to_have_attribute(
                "data-state", "active"
            )
            platform = next(
                item
                for item in api("/platforms")
                if item["adapter_status"] == "available"
                and item["concurrency_range"]["max"] > item["concurrency_range"]["min"]
            )
            card = (
                page.get_by_role("tabpanel", name="平台配置", exact=True)
                .locator("[data-slot=card]")
                .filter(has=page.get_by_text(platform["display_name"], exact=True))
            )
            number = card.locator("input[type=number]:enabled:visible")
            number.wait_for()
            baseline = number.input_value()
            if args.isolated_writes:
                minimum = int(number.get_attribute("min"))
                maximum = int(number.get_attribute("max"))
                changed = str(minimum if int(baseline) != minimum else min(maximum, minimum + 1))
                assert changed != baseline
                number.fill(changed)
                save = page.get_by_role("button", name=re.compile("保存当前标签"))
                expect(save).to_be_enabled()
                save.click()
                expect(save).to_be_disabled()
                page.reload()
                expect(number).to_have_value(changed)
                number.fill(baseline)
                save.click()
                expect(save).to_be_disabled()
                passed("config-save-reload-and-restore", baseline=baseline, tested=changed)
            shot(page, "config-platforms")

            # 认证只验证同一真实 Dialog 的故障态；浏览器路由拦截避免触发外部平台。
            page.route(
                "**/api/v1/platforms/*/auth/tasks*",
                lambda route: route.fulfill(
                    status=503,
                    content_type="application/json",
                    body=json.dumps(
                        {
                            "code": "UI_TEST_AUTH_OFFLINE",
                            "message": "浏览器验收：隔离认证连接不可用。",
                        }
                    ),
                ),
            )
            auth = page.get_by_role(
                "button", name=re.compile("获取 Session|更新 Session|初始化|更新会话")
            ).first
            auth.click()
            expect(page.get_by_role("dialog")).to_be_visible()
            expect(page.get_by_text("UI_TEST_AUTH_OFFLINE", exact=False)).to_be_visible()
            rect = page.get_by_role("dialog").bounding_box()
            assert rect["width"] > 1440 * 0.8
            shot(page, "auth-dialog-error-fixture")
            page.keyboard.press("Escape")
            expect(page.get_by_role("dialog")).to_have_count(0)
            passed(
                "auth-dialog-error-focus-and-close", data_source="browser fixture; no platform call"
            )

            page.goto(base + "/runs")
            toggle = page.get_by_role("button", name="展开或收起导航")
            toggle.click()
            expect(page.locator("[data-collapsible=icon]")).to_have_count(1)
            expect(page.locator(".tactile-edition")).to_have_count(0)
            page.reload()
            expect(page.locator("[data-collapsible=icon]")).to_have_count(1)
            page.locator('[data-list-viewport="runs"] tbody tr').first.wait_for()
            shot(page, "sidebar-collapsed")
            no_overflow(page)
            toggle.click()
            passed("sidebar-collapse-persistence-and-expand")

            page.goto(base + "/")
            page.locator(".home-batch").first.wait_for()
            for theme in ("dark", "light"):
                page.get_by_role("button", name="切换显示主题").click()
                page.get_by_role(
                    "menuitem", name="深色主题" if theme == "dark" else "浅色主题"
                ).click()
                expect(page.locator("html")).to_have_class(theme)
                shot(page, f"theme-{theme}")
            passed("theme-switch-and-portal")

            expect(page.locator(".tactile-edition, .tactile-sculpture-control")).to_have_count(0)
            expect(page.get_by_text("有形的反馈。", exact=False)).to_have_count(0)
            expect(page.get_by_text("TACTILE EDITION", exact=False)).to_have_count(0)
            expect(page.locator(".tactile-nav-item")).to_have_count(5)
            expect(page.locator(".tactile-brand-copy")).to_be_visible()
            expect(page.locator(".tactile-connection")).to_be_visible()
            expect(page.locator('.tactile-root a[href="/classic.html"]')).to_have_count(0)
            passed("sidebar-promo-removed-brand-navigation-and-connection-preserved")

            page.goto(base + "/classic.html")
            page.wait_for_url("**/classic.html*")
            expect(page.locator(".workspace-app-root")).to_be_visible()
            assert page.locator(".tactile-root").count() == 0
            page.get_by_role("link", name=re.compile("循环计划")).click()
            page.wait_for_url("**/classic.html#/recurring-runs*")
            page.reload()
            expect(page.locator(".workspace-app-root")).to_be_visible()
            shot(page, "classic-production")
            page.goto(base + "/tactile.html#/runs")
            expect(page.locator(".tactile-root")).to_be_visible()
            page.get_by_role("link", name="循环计划", exact=True).click()
            page.wait_for_url("**/tactile.html#/recurring-runs*")
            passed("classic-and-tactile-production-build-and-hash-navigation")

            for width, height in [(1280, 900), (1024, 900), (768, 1024), (390, 844), (844, 390)]:
                c = browser.new_context(
                    viewport={"width": width, "height": height}, color_scheme="light"
                )
                m = c.new_page()
                m.on("pageerror", lambda e: report["page_errors"].append(str(e)))
                m.goto(base + "/")
                m.locator(".home-batch").first.wait_for()
                no_overflow(m)
                shot(m, f"home-{width}")
                m.goto(base + "/runs")
                m.locator('[data-list-viewport="runs"] tbody tr').first.wait_for()
                no_overflow(m)
                assert m.locator(".workspace-visual").count() == 0
                rect = m.get_by_role("button", name="新建提取", exact=True).bounding_box()
                assert rect and rect["y"] + rect["height"] <= height
                if width < 768:
                    m.get_by_role("button", name="展开或收起导航").click()
                    expect(m.get_by_role("dialog")).to_be_visible()
                    m.get_by_role("dialog").get_by_role("link", name="循环计划", exact=True).click()
                    m.wait_for_url("**/recurring-runs*")
                    expect(m.get_by_role("dialog")).to_have_count(0)
                shot(m, f"responsive-{width}")
                # 缩窄后仍可滚动到主操作，表格保留自己的横向滚动。
                m.goto(base + "/runs")
                m.get_by_role("button", name="新建提取", exact=True).click()
                expect(m.get_by_role("button", name="提交提取", exact=True)).to_be_visible()
                no_overflow(m)
                shot(m, f"form-{width}")
                c.close()
                passed(f"responsive-{width}-navigation-and-form")

            c = browser.new_context(
                viewport={"width": 1440, "height": 900},
                reduced_motion="reduce",
                color_scheme="dark",
            )
            reduced = c.new_page()
            reduced.goto(base + "/")
            reduced.locator(".home-batch").first.wait_for()
            expect(reduced.locator(".tactile-edition, [data-sculpture-piece]")).to_have_count(0)
            expect(reduced.locator(".home-metric")).to_have_count(3)
            expect(reduced.locator(".tactile-nav-item")).to_have_count(5)
            c.close()
            passed("reduced-motion-sidebar-and-home-preserved")

            for state in ("empty", "error"):
                c = browser.new_context()
                edge = c.new_page()
                edge.route(
                    "**/api/v1/dashboard",
                    lambda route: route.fulfill(
                        status=200 if state == "empty" else 503,
                        content_type="application/json",
                        body=json.dumps(
                            {
                                "date": "2026-09-07",
                                "timezone": "Asia/Shanghai",
                                "generated_at": "2026-09-07T02:00:00Z",
                                "categories": [
                                    {
                                        "key": k,
                                        "label": k,
                                        "total": 0,
                                        "today": 0,
                                        "active": 0,
                                        "attention": 0,
                                        "recent": [],
                                        "attention_items": [],
                                    }
                                    for k in ["extraction", "recurring", "reputation"]
                                ],
                            }
                            if state == "empty"
                            else {"code": "UI_TEST_OFFLINE", "message": "隔离错误状态测试"}
                        ),
                    ),
                )
                edge.goto(base + "/")
                expect(
                    edge.locator('[data-home-total="extraction"] [data-count-value]')
                ).to_have_text("0" if state == "empty" else "—")
                assert edge.locator('.home-batch[aria-pressed="true"]').count() == 0
                shot(edge, f"fixture-{state}")
                c.close()
                passed(f"{state}-not-confused-with-real-data", data_source="browser fixture")
            assert not report["page_errors"], report["page_errors"]
            passed("no-page-javascript-errors")
            report["status"] = "passed"
        except Exception as error:
            report["status"] = "failed"
            report["failure"] = str(error)
            shot(page, "failure")
            raise
        finally:
            (args.output / "verification.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            browser.close()


if __name__ == "__main__":
    main()
