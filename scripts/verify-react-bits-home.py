"""React Bits 首页局部增强验收；真实首页只读，刷新/失败测试仅拦截浏览器响应。"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:5173")
    parser.add_argument(
        "--output", type=Path, default=Path("artifacts/runtime/react-bits-home/live")
    )
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    base = args.base_url.rstrip("/")
    report = {"base_url": base, "checks": [], "page_errors": [], "writes": []}

    def passed(name, **details):
        report["checks"].append({"name": name, "status": "passed", **details})
        print("PASS", name, flush=True)

    def watch(page):
        page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
        page.on(
            "request",
            lambda request: (
                report["writes"].append(request.url)
                if request.url.startswith(base + "/api/") and request.method not in ("GET", "HEAD")
                else None
            ),
        )

    def value(page, key="extraction"):
        return page.locator(f'[data-home-total="{key}"] [data-count-value]')

    def shot(page, name):
        page.screenshot(path=str(args.output / f"{name}.png"), animations="disabled")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            request = browser.new_context().request
            response = request.get(base + "/api/v1/dashboard")
            assert response.ok, response.status
            original = response.json()
            for theme in ("light", "dark"):
                context = browser.new_context(
                    viewport={"width": 1440, "height": 1050}, color_scheme=theme
                )
                page = context.new_page()
                watch(page)
                page.goto(base + "/")
                for category in original["categories"]:
                    expect(value(page, category["key"])).to_have_text(str(category["total"]))
                    expect(
                        page.locator(f'[data-home-total="{category["key"]}"] .sr-only')
                    ).to_have_text(str(category["total"]))
                page.wait_for_timeout(750)
                assert page.locator("canvas").count() == 0
                # 按表面渐变两端、静态光斑与指针光晕同时最亮的保守组合核验小字。
                colors = page.locator(".home-metric").evaluate_all("""items => items.map(e => {
                  const c=document.createElement('canvas').getContext('2d'), s=getComputedStyle(e);
                  const rgba=color=>{c.clearRect(0,0,1,1); c.fillStyle=color; c.fillRect(0,0,1,1); return [...c.getImageData(0,0,1,1).data]};
                  const resolve=key=>rgba(s.getPropertyValue(key));
                  return {text:rgba(getComputedStyle(e.querySelector('dt')).color),
                    backgrounds:[resolve('--card'),resolve('--home-raised')],
                    ambient:.09, primary:resolve('--primary'),spot:resolve('--spotlight-color')};
                })""")

                def luminance(rgb):
                    linear = [
                        (v / 255) / 12.92
                        if v / 255 <= 0.04045
                        else ((v / 255 + 0.055) / 1.055) ** 2.4
                        for v in rgb[:3]
                    ]
                    return sum(v * w for v, w in zip(linear, (0.2126, 0.7152, 0.0722)))

                ratios = []
                for item in colors:
                    for background in item["backgrounds"]:
                        a = item["ambient"]
                        ambient = [
                            background[i] * (1 - a) + item["primary"][i] * a for i in range(3)
                        ]
                        opacity = item["spot"][3] / 255
                        composed = [
                            ambient[i] * (1 - opacity) + item["spot"][i] * opacity for i in range(3)
                        ]
                        foreground, backdrop = luminance(item["text"]), luminance(composed)
                        ratios.append(
                            (max(foreground, backdrop) + 0.05) / (min(foreground, backdrop) + 0.05)
                        )
                assert min(ratios) >= 4.5, ratios
                passed(
                    f"spotlight-label-contrast-{theme}",
                    minimum=round(min(ratios), 2),
                    surface_samples=len(ratios),
                )
                card = page.locator(".home-metric").first
                layer = card.locator("[data-spotlight-layer]")
                before = card.bounding_box()
                card.hover(position={"x": 55, "y": 60})
                expect(layer).to_have_css("opacity", "1")
                first = card.evaluate("e => e.style.getPropertyValue('--spotlight-x')")
                card.hover(position={"x": 180, "y": 105})
                expect(layer).to_have_css("opacity", "1")
                second = card.evaluate("e => e.style.getPropertyValue('--spotlight-x')")
                assert first != second
                assert card.bounding_box() == before, "光晕不应移动或扩大卡片"
                assert layer.evaluate("e => getComputedStyle(e).pointerEvents") == "none"
                shot(page, f"home-{theme}-spotlight")
                page.mouse.move(3, 3)
                expect(layer).to_have_css("opacity", "0")
                passed(
                    f"real-home-pointer-values-{theme}",
                    categories=len(original["categories"]),
                    positions=[first, second],
                )

                expect(page.locator(".tactile-edition, .tactile-sculpture-control")).to_have_count(
                    0
                )
                expect(page.locator(".bits-spotlight")).to_have_count(3)
                expect(page.locator(".tactile-brand-copy")).to_be_visible()
                passed(f"sidebar-promo-removed-home-effects-preserved-{theme}")
                page.get_by_role("link", name="提取列表", exact=True).click()
                expect(page.locator(".home-page")).to_have_count(0)
                assert page.locator(".tactile-content .bits-spotlight").count() == 0
                assert page.locator(".tactile-content .bits-count").count() == 0
                passed(f"no-effects-in-business-list-{theme}")
                context.close()

            # 仅浏览器替身：先保留请求，验证未知状态，再观测数字动画的实际中间帧。
            fixture = copy.deepcopy(original)
            for category in fixture["categories"]:
                category["total"] = {"extraction": 240, "recurring": 0, "reputation": 17}[
                    category["key"]
                ]
            context = browser.new_context(viewport={"width": 1440, "height": 1050})
            page = context.new_page()
            watch(page)
            pending = []
            page.route("**/api/v1/dashboard", lambda route: pending.append(route))
            page.goto(base + "/", wait_until="domcontentloaded")
            expect(value(page)).to_have_text("—")
            page.wait_for_timeout(150)
            assert pending, "首页请求尚未进入替身"
            value(page).evaluate(
                "e => {window.countFrames=[];new MutationObserver(() => window.countFrames.push({text:e.textContent, width:e.parentElement.getBoundingClientRect().width})).observe(e,{childList:true,subtree:true,characterData:true})}"
            )
            pending.pop(0).fulfill(json=fixture)
            page.wait_for_function(
                "document.querySelector('[data-home-total=extraction] [data-count-value]')?.dataset.countAnimating === 'true'"
            )
            expect(page.locator('[data-home-total="extraction"] .sr-only')).to_have_text("240")
            page.wait_for_timeout(800)
            expect(value(page)).to_have_text("240")
            expect(value(page, "recurring")).to_have_text("0")
            frames = page.evaluate("window.countFrames")
            numeric = [int(item["text"]) for item in frames if item["text"].isdigit()]
            assert any(0 < number < 240 for number in numeric), numeric
            widths = [item["width"] for item in frames if item["text"].isdigit()]
            assert max(widths) - min(widths) < 1, widths
            assert value(page, "recurring").get_attribute("data-count-animating") != "true"
            passed(
                "known-value-first-animation-zero-and-width",
                source="browser fixture",
                frames=numeric,
                width_range=[min(widths), max(widths)],
            )

            def refresh(total):
                fixture["categories"][0]["total"] = total
                page.get_by_role("button", name="刷新首页", exact=True).click()
                page.wait_for_timeout(100)
                assert pending
                pending.pop(0).fulfill(json=fixture)
                expect(value(page)).to_have_text(str(total))
                assert value(page).get_attribute("data-count-animating") != "true"

            page.evaluate("window.countFrames=[]")
            refresh(240)
            refresh(245)
            assert all(
                item["text"] in ("240", "245") for item in page.evaluate("window.countFrames")
            )
            passed("refresh-and-new-data-do-not-replay", source="browser fixture")
            # 失败期间显示未知，恢复后不重新播放；重试请求也在浏览器内返回错误。
            page.unroute("**/api/v1/dashboard")
            page.route(
                "**/api/v1/dashboard",
                lambda route: route.fulfill(status=503, json={"detail": "测试首页暂不可用"}),
            )
            page.get_by_role("button", name="刷新首页", exact=True).click()
            expect(page.get_by_role("alert")).to_be_visible(timeout=15000)
            expect(value(page)).to_have_text("—")
            page.unroute("**/api/v1/dashboard")
            page.route("**/api/v1/dashboard", lambda route: route.fulfill(json=fixture))
            page.get_by_role("button", name="重试", exact=True).click()
            expect(value(page)).to_have_text("245")
            assert value(page).get_attribute("data-count-animating") != "true"
            passed("error-recovery-retains-real-value-contract", source="browser fixture")
            context.close()

            for stop in ("offscreen", "hidden", "unmount"):
                context = browser.new_context(viewport={"width": 1440, "height": 1050})
                page = context.new_page()
                watch(page)
                page.route("**/api/v1/dashboard", lambda route: route.fulfill(json=fixture))
                page.goto(base + "/")
                page.wait_for_function(
                    "document.querySelector('[data-home-total=extraction] [data-count-value]')?.dataset.countAnimating === 'true'"
                )
                value(page).evaluate(
                    "e => {window.detachedWrites=0;new MutationObserver(() => window.detachedWrites++).observe(e,{childList:true,subtree:true,characterData:true})}"
                )
                if stop == "offscreen":
                    page.locator(".home-page").evaluate("e => e.scrollTop=900")
                    expect(value(page)).to_have_attribute("data-count-animating", "false")
                    page.locator(".home-page").evaluate("e => e.scrollTop=0")
                    expect(value(page)).to_have_text("245")
                    assert value(page).get_attribute("data-count-animating") != "true"
                elif stop == "hidden":
                    page.evaluate(
                        "Object.defineProperty(document,'hidden',{configurable:true,get:()=>true}); document.dispatchEvent(new Event('visibilitychange'))"
                    )
                    expect(value(page)).to_have_attribute("data-count-animating", "false")
                    expect(value(page)).to_have_text("245")
                else:
                    page.get_by_role("link", name="提取列表", exact=True).click()
                    expect(page.locator(".home-page")).to_have_count(0)
                page.wait_for_timeout(50)
                writes = page.evaluate("window.detachedWrites")
                page.wait_for_timeout(800)
                assert page.evaluate("window.detachedWrites") == writes, "停止后仍有数值动画写入"
                passed(
                    f"count-stops-on-{stop}",
                    source="browser fixture"
                    if stop == "hidden"
                    else "rendered page with fixture data",
                )
                context.close()

            for mode, options in [
                (
                    "reduced",
                    {"viewport": {"width": 1440, "height": 1050}, "reduced_motion": "reduce"},
                ),
                (
                    "touch",
                    {
                        "viewport": {"width": 390, "height": 844},
                        "is_mobile": True,
                        "has_touch": True,
                        "device_scale_factor": 1,
                    },
                ),
            ]:
                context = browser.new_context(**options)
                page = context.new_page()
                watch(page)
                page.goto(base + "/")
                expect(value(page)).to_have_text(str(original["categories"][0]["total"]))
                page.wait_for_timeout(750)
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                assert page.locator(".home-metric [data-count-value]").count() == 3
                if mode == "reduced":
                    page.locator(".home-metric").first.hover()
                    expect(page.locator(".home-metric [data-spotlight-layer]").first).to_have_css(
                        "display", "none"
                    )
                    assert page.locator('[data-count-animating="true"]').count() == 0
                    expect(page.locator(".tactile-edition")).to_have_count(0)
                else:
                    page.locator(".home-metric").first.tap()
                    assert page.locator('.home-metric[data-spotlight-active="true"]').count() == 0
                    expect(page.get_by_role("button", name="刷新首页", exact=True)).to_be_visible()
                shot(page, mode)
                passed(f"{mode}-static-equivalent-readable")
                context.close()

            license = request.get(base + "/third-party/react-bits.txt")
            assert (
                license.ok
                and "MIT + Commons Clause" in license.text()
                and "2026 David Haz" in license.text()
            )
            passed("license-shipped-with-frontend")
            assert not report["writes"], report["writes"]
            assert not report["page_errors"], report["page_errors"]
            passed("no-business-writes-or-javascript-errors")
            report["status"] = "passed"
        except Exception as error:
            report.update(status="failed", error=str(error))
            if "page" in locals() and not page.is_closed():
                shot(page, "failure")
            raise
        finally:
            (args.output / "verification.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            browser.close()


if __name__ == "__main__":
    main()
