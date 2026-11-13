"""Real configuration, lifecycle and dependency refusals from the market controls."""

import asyncio
import json
import tomllib
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.async_api import async_playwright, expect
from served import admin, client, serving
from test_market import FINISHED


async def test_entry_switch_and_dependency_refusal(home: Path):
    async with serving(home) as served, client() as boss, async_playwright() as driver:
        await admin(served, boss)
        browser = await driver.chromium.launch()
        try:
            context = await browser.new_context(locale="zh-CN")
            await context.add_cookies(
                [
                    {"name": item.name, "value": item.value or "", "url": served.url}
                    for item in boss.cookies.jar
                ]
            )
            page = await context.new_page()
            await page.goto(served.url + "/market?computer=server&view=installed")
            frame = page.frame_locator("iframe.frame")
            for label, expected, phase in (
                ("logging 未启用", "logging 已启用", "complete"),
                ("logging 已启用", "logging 未启用", "complete"),
                ("status 已启用", "status 已启用", "failed"),
            ):
                before = await asyncio.to_thread((home / "server.toml").read_bytes)
                async with page.expect_response(
                    lambda response: (
                        response.request.method == "POST"
                        and urlsplit(response.url).path == "/ui/market/change"
                    )
                ) as submitted:
                    await frame.get_by_role("switch", name=label, exact=True).click()
                response = await submitted.value
                assert response.status == 200
                operation = parse_qs(urlsplit(response.headers["hx-push-url"]).query)[
                    "operation"
                ][0]
                await expect(
                    frame.locator("#operation .operation-heading code")
                ).to_have_text(operation)
                while True:
                    result = (
                        await boss.get(
                            served.url + "/api/market/server/operations/" + operation
                        )
                    ).json()
                    if result["phase"] in FINISHED:
                        break
                    await asyncio.sleep(0.1)
                assert result["phase"] == phase, result
                await expect(frame.locator("#operation:not([hx-get])")).to_be_visible()
                await expect(
                    frame.get_by_role("switch", name=expected, exact=True)
                ).to_be_visible()
                if phase == "failed":
                    assert not result["config_saved"]
                    assert (
                        await asyncio.to_thread((home / "server.toml").read_bytes)
                        == before
                    )
        finally:
            await browser.close()


async def test_index_subscription_add_view_refresh_and_remove(home: Path):
    index = home / "local-modules.json"
    document = {
        "contribs": [
            {
                "package": "bazaar-contrib-logging",
                "source": "https://pypi.org/simple/",
                "summary": "Modules maintained on this computer",
            },
            {
                "package": "bazaar-contrib-server-usage",
                "source": "https://pypi.org/simple/",
            },
        ]
    }
    await asyncio.to_thread(index.write_text, json.dumps(document))
    async with serving(home) as served, client() as boss, async_playwright() as driver:
        await admin(served, boss)
        browser = await driver.chromium.launch()
        try:
            context = await browser.new_context(locale="zh-CN")
            await context.add_cookies(
                [
                    {"name": item.name, "value": item.value or "", "url": served.url}
                    for item in boss.cookies.jar
                ]
            )
            page = await context.new_page()
            await page.goto(served.url + "/market?computer=server&view=indexes")
            frame = page.frame_locator("iframe.frame")
            await frame.get_by_label("本地路径或 HTTP(S) 索引地址").fill(str(index))
            await frame.get_by_role("button", name="添加索引", exact=True).click()
            row = frame.locator(".index-row").filter(has_text=str(index))
            await expect(row).to_contain_text("已读取")
            await row.get_by_role("link", name=index.name, exact=True).click()
            await expect(frame.locator(".index-detail")).to_contain_text(
                document["contribs"][0]["summary"]
            )
            await (
                frame.locator(".index-detail")
                .get_by_role("heading", name="server-usage", exact=True)
                .get_by_role("link")
                .click()
            )
            await expect(frame.locator("#package h2")).to_have_text(
                "bazaar-contrib-server-usage"
            )
            await expect(
                frame.get_by_role("button", name="安装", exact=True)
            ).to_be_visible()
            await frame.locator(".index-link").click()
            await (
                frame.locator(".index-detail .package-card")
                .filter(has_text="server-usage")
                .locator("a.install")
                .click()
            )
            await expect(frame.locator("#package h2")).to_have_text(
                "bazaar-contrib-server-usage"
            )
            await expect(
                frame.get_by_role("button", name="安装", exact=True)
            ).to_be_visible()
            await frame.locator(".index-link").click()
            document["contribs"][0]["summary"] = "Updated local modules"
            await asyncio.to_thread(index.write_text, json.dumps(document))
            await frame.get_by_role("button", name="刷新索引", exact=True).click()
            await expect(frame.locator(".index-detail")).to_contain_text(
                "Updated local modules"
            )
            await row.get_by_role("button", name="移除", exact=True).click()
            await expect(row).to_have_count(0)
            saved = tomllib.loads(
                await asyncio.to_thread((home / "server.toml").read_text)
            )
            assert str(index) not in saved["contrib_indexes"]
        finally:
            await browser.close()
