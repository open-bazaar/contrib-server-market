"""The real market in the desktop shell and the phone's navigation."""

from pathlib import Path

import pytest
from playwright.async_api import async_playwright, expect
from served import admin, client, enrol, serving


@pytest.mark.parametrize("size", [(1440, 900), (390, 844)], ids=["desktop", "phone"])
async def test_offline_computer_can_switch_to_server(home: Path, size: tuple[int, int]):
    async with serving(home) as served, client() as boss, async_playwright() as driver:
        await admin(served, boss)
        ref, _ = await enrol(served, boss, "Offline computer")
        browser = await driver.chromium.launch()
        try:
            context = await browser.new_context(
                locale="en-US", viewport={"width": size[0], "height": size[1]}
            )
            await context.add_cookies(
                [
                    {
                        "name": cookie.name,
                        "value": cookie.value or "",
                        "url": served.url,
                    }
                    for cookie in boss.cookies.jar
                ]
            )
            page = await context.new_page()
            await page.goto(f"{served.url}/market")
            frame = page.frame_locator("iframe.frame")
            await expect(frame.locator(".unavailable")).to_contain_text(
                "Connect this computer to browse its Contribs."
            )
            await frame.locator("#target-button").click()
            offline = frame.locator("#target-menu .target-option").filter(
                has_text="Offline computer"
            )
            await expect(offline).to_contain_text("Offline")
            await expect(offline).not_to_contain_text("0 installed")
            await (
                frame.locator("#target-menu")
                .get_by_role("link", name="Bazaar Server", exact=False)
                .click()
            )
            await expect(frame.locator(".installed-packages")).to_contain_text(
                "server-market"
            )
            await frame.locator("#target-button").press("Escape")
            await expect(frame.locator("#target-menu")).to_be_hidden()
            await frame.locator("#target-button").click()
            await (
                frame.locator("#target-menu .target-option")
                .filter(has_text="Offline computer")
                .click()
            )
            await expect(frame.locator(".unavailable")).to_be_visible()
            content = next(one for one in page.frames if "/ui/market/" in one.url)
            assert f"computer={ref}" in content.url
            assert await content.evaluate(
                "document.documentElement.scrollWidth <= innerWidth"
            )
        finally:
            await browser.close()


@pytest.mark.parametrize(
    "size", [(1440, 900), (850, 900), (390, 844)], ids=["desktop", "tablet", "phone"]
)
async def test_market_navigation_detail_and_input_errors(
    home: Path, size: tuple[int, int]
):
    async with serving(home) as served, client() as boss, async_playwright() as driver:
        await admin(served, boss)
        browser = await driver.chromium.launch()
        try:
            context = await browser.new_context(
                locale="zh-CN", viewport={"width": size[0], "height": size[1]}
            )
            await context.add_cookies(
                [
                    {
                        "name": cookie.name,
                        "value": cookie.value or "",
                        "url": served.url,
                    }
                    for cookie in boss.cookies.jar
                ]
            )
            page = await context.new_page()
            await page.goto(f"{served.url}/market")
            frame = page.frame_locator("iframe.frame")
            await expect(
                frame.get_by_role("heading", name="市场", exact=True)
            ).to_be_visible()
            await expect(frame.get_by_label("当前管理对象")).to_contain_text(
                "Bazaar Server"
            )
            # On a phone the shell puts the fifth and later destinations in More.
            if size[0] < 700:
                more = page.locator("label[for=more-places]")
                if await more.count():
                    await more.click()
            await expect(
                page.get_by_role("link", name="市场", exact=True)
            ).to_be_visible()
            async with page.expect_event(
                "framenavigated",
                predicate=lambda one: (
                    one.parent_frame is not None and "/ui/market" in one.url
                ),
            ):
                await page.get_by_role("link", name="市场", exact=True).click()
            await (
                frame.get_by_role("heading", name="manager", exact=True)
                .get_by_role("link")
                .click()
            )
            await expect(frame.locator("#package")).to_contain_text(
                "bazaar-contrib-manager"
            )
            await expect(frame.locator("#package")).to_contain_text("依赖兼容要求")
            await frame.get_by_label("版本要求").fill("not a version")
            await frame.get_by_role("button", name="安装", exact=True).click()
            await expect(frame.locator("#operation")).to_contain_text("请求未能提交")
            content = next(one for one in page.frames if "/ui/market/" in one.url)
            assert await content.evaluate(
                "document.documentElement.scrollWidth <= innerWidth"
            )
            await frame.get_by_role("link", name="已安装").first.click()
            await expect(frame.locator(".installed-packages")).to_contain_text(
                "server-market"
            )
            if size[0] >= 960:
                await frame.get_by_role("link", name="Server 设置", exact=True).click()
                await page.wait_for_url("**/settings")
                await expect(
                    frame.get_by_role("heading", name="设置", exact=True)
                ).to_be_visible()

        finally:
            await browser.close()
