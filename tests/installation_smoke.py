"""Exercise the public market from a dedicated installed server interpreter."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import threading
import tomllib
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.async_api import async_playwright, expect
from served import admin, client, serving
from test_market import FINISHED, computer, result


class Registry(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass


async def changed(page, button, boss, api):
    async with page.expect_response(
        lambda response: (
            response.request.method == "POST"
            and urlsplit(response.url).path == "/ui/market/change"
        )
    ) as submitted:
        await button.click()
    response = await submitted.value
    assert response.status == 200
    operation = parse_qs(urlsplit(response.headers["hx-push-url"]).query)["operation"][
        0
    ]
    frame = page.frame_locator("iframe.frame")
    await expect(frame.locator("#operation .operation-heading code")).to_have_text(
        operation
    )
    while True:
        response = (await boss.get(f"{api}/operations/{operation}")).json()
        if response["phase"] in FINISHED:
            frame = page.frame_locator("iframe.frame")
            await expect(
                frame.locator("#operation .operation-heading code")
            ).to_have_text(operation)
            await expect(frame.locator("#operation:not([hx-get])")).to_be_visible()
            await expect(frame.locator("#packages")).to_have_attribute(
                "data-updates", "ready"
            )
            return response
        await asyncio.sleep(0.1)


async def exercise() -> None:
    home, node_python, other_python, wheels = map(Path, sys.argv[1:])
    home.mkdir()
    os.environ.update(BCN_HOME=str(home), HOME=str(home), USERPROFILE=str(home))
    registry = home / "registry"
    files = registry / "files"
    files.mkdir(parents=True)
    wheel = next(wheels.glob("bazaar_contrib_market_example-0.1.0-*.whl"))
    shutil.copy(wheel, files / wheel.name)
    simple = registry / "simple/bazaar-contrib-market-example"
    simple.mkdir(parents=True)
    (simple / "index.html").write_text(
        f'<a href="../../files/{wheel.name}">{wheel.name}</a>'
    )
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), partial(Registry, directory=str(registry))
    )
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    source = f"http://127.0.0.1:{server.server_port}/simple/"
    alternate_source = f"http://127.0.0.1:{server.server_port}/alternate/"
    alternate = registry / "alternate/bazaar-contrib-market-example"
    alternate.mkdir(parents=True)
    (alternate / "index.html").write_text(
        f'<a href="../../files/{wheel.name}">{wheel.name}</a>'
    )
    try:
        async with (
            serving(home) as served,
            client() as boss,
            async_playwright() as driver,
        ):
            await admin(served, boss)
            browser = await driver.chromium.launch()
            context = await browser.new_context(locale="zh-CN")
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
            async with (
                computer(
                    served, boss, home / "computer", "Install here", python=node_python
                ) as (ref, config),
                computer(
                    served, boss, home / "other", "Leave unchanged", python=other_python
                ) as (other, other_config),
            ):
                original = other_config.read_bytes()
                untouched = (
                    await boss.get(
                        f"{served.url}/api/market/computers/{other}/installed"
                    )
                ).json()
                report = {}
                for name, selected, path, api in (
                    ("server", "server", home, f"{served.url}/api/market/server"),
                    (
                        "computer",
                        ref,
                        config.parent,
                        f"{served.url}/api/market/computers/{ref}",
                    ),
                ):
                    index = path / "extra.json"
                    index.write_text(
                        json.dumps(
                            {
                                "contribs": [
                                    {
                                        "package": "bazaar-contrib-market-example",
                                        "source": source,
                                        "summary": "A private Contrib",
                                    },
                                    {
                                        "package": "bazaar-contrib-server-usage",
                                        "source": "https://pypi.org/simple/",
                                    },
                                ]
                            }
                        )
                    )
                    await result(
                        boss,
                        api,
                        await boss.post(
                            api + "/indexes", json={"location": str(index)}
                        ),
                    )
                    if name == "computer":
                        document = json.loads(index.read_text())
                        document["contribs"].append(
                            {
                                "package": "bazaar-contrib-codex",
                                "source": "https://pypi.org/simple/",
                            }
                        )
                        index.write_text(json.dumps(document))
                        await boss.post(api + "/indexes/refresh")
                    report[name] = {}
                    for label, package in (
                        ("private", "bazaar-contrib-market-example"),
                        (
                            "public",
                            "bazaar-contrib-server-usage",
                        ),
                    ):
                        await page.goto(
                            f"{served.url}/market?computer={selected}&view=catalog"
                            + ("&state=available" if label == "public" else "")
                        )
                        frame = page.frame_locator("iframe.frame")
                        installed_before = int(
                            await frame.locator("#installed-count").inner_text()
                        )
                        await (
                            frame.get_by_role(
                                "heading",
                                name=package.removeprefix("bazaar-contrib-"),
                                exact=True,
                            )
                            .get_by_role("link")
                            .click()
                        )
                        if label == "private":
                            await frame.get_by_label("版本要求").fill(">=0.1.0")
                        async with page.expect_response(
                            lambda response: (
                                "/ui/market/install?" in response.url
                                and response.request.method == "POST"
                            )
                        ) as submitted:
                            await frame.get_by_role(
                                "button", name="安装", exact=True
                            ).click()
                        response = await submitted.value
                        assert response.status == 200
                        address = response.headers["hx-push-url"]
                        operation_id = parse_qs(urlsplit(address).query)["operation"][0]
                        await page.wait_for_url(
                            lambda address, operation_id=operation_id: (
                                operation_id in address
                            )
                        )
                        if label == "private":
                            async with page.expect_event(
                                "requestfailed",
                                predicate=lambda request, operation_id=operation_id: (
                                    f"/ui/market/operations/{operation_id}"
                                    in request.url
                                ),
                            ):
                                await context.set_offline(True)
                            await expect(frame.locator("#operation")).to_be_visible()
                            await context.set_offline(False)
                            await page.reload()
                        operation = (
                            await boss.get(f"{api}/operations/{operation_id}")
                        ).json()
                        while operation["phase"] not in FINISHED:
                            await asyncio.sleep(0.1)
                            operation = (
                                await boss.get(f"{api}/operations/{operation_id}")
                            ).json()
                        assert operation["phase"] == "complete", operation
                        assert operation["installed"] and operation["config_saved"]
                        await expect(frame.locator("#operation")).to_contain_text(
                            "包安装完成"
                        )
                        installed = (await boss.get(f"{api}/installed")).json()
                        assert len(installed) > installed_before
                        await expect(frame.locator("#installed-count")).to_have_text(
                            str(len(installed))
                        )
                        card = frame.locator(".package-card").filter(
                            has=frame.get_by_role(
                                "heading",
                                name=package.removeprefix("bazaar-contrib-"),
                                exact=True,
                            )
                        )
                        if label == "public":
                            await expect(card).to_have_count(0)
                        else:
                            await expect(card.locator(".package-status")).to_have_text(
                                "已安装"
                            )
                        await page.reload()
                        await expect(frame.locator("#operation")).to_contain_text(
                            "包安装完成"
                        )
                        # Reloading the persisted operation restores actual metadata.
                        restored = await boss.get(served.url + address)
                        assert restored.status_code == 200, restored.text
                        assert package in restored.text
                        metadata = (await boss.get(f"{api}/packages/{package}")).json()
                        assert metadata["entries"] and metadata["requirements"]
                        if label == "private":
                            assert any(
                                entry["config_schema"]
                                .get("properties", {})
                                .get("message")
                                for entry in metadata["entries"]
                            )
                        report[name][label] = metadata["version"]
                        if label == "private":
                            document = json.loads(index.read_text())
                            document["contribs"].append(
                                {
                                    "package": package,
                                    "source": alternate_source,
                                    "summary": "An alternative Contrib source",
                                }
                            )
                            index.write_text(json.dumps(document))
                            assert (
                                await boss.post(api + "/indexes/refresh")
                            ).status_code == 200
                            duplicates = [
                                item["source"]
                                for item in (await boss.get(api + "/catalog")).json()
                                if item["package"] == package
                            ]
                            assert duplicates == [alternate_source, source]
                            await page.goto(
                                f"{served.url}/market?computer={selected}&view=catalog&q=market-example"
                            )
                            alternative = frame.locator(".package-card").filter(
                                has_text="An alternative Contrib source"
                            )
                            await (
                                alternative.get_by_role("heading")
                                .get_by_role("link")
                                .click()
                            )
                            await expect(
                                frame.locator('#package input[name="source"]')
                            ).to_have_value(alternate_source)
                            await page.goto(
                                f"{served.url}/market?computer={selected}&view=installed&q=market-example"
                            )
                            await (
                                frame.get_by_role(
                                    "heading", name="market-example", exact=True
                                )
                                .get_by_role("link")
                                .click()
                            )
                            await expect(frame.locator("#package")).to_contain_text(
                                "A private Contrib"
                            )
                            await expect(
                                frame.locator('#package input[name="source"]')
                            ).to_have_value(source)
                            await frame.get_by_label("版本要求").fill(">=0.1.0")
                            async with page.expect_response(
                                lambda response: (
                                    "/ui/market/install?" in response.url
                                    and response.request.method == "POST"
                                )
                            ) as submitted:
                                await frame.get_by_role(
                                    "button", name="安装", exact=True
                                ).click()
                            response = await submitted.value
                            assert parse_qs(response.request.post_data or "")[
                                "source"
                            ] == [source]
                            operation_id = parse_qs(
                                urlsplit(response.headers["hx-push-url"]).query
                            )["operation"][0]
                            await result(
                                boss,
                                api,
                                await boss.get(f"{api}/operations/{operation_id}"),
                            )
                            await expect(
                                frame.locator("#operation .operation-heading code")
                            ).to_have_text(operation_id)
                            await expect(
                                frame.locator("#operation:not([hx-get])")
                            ).to_be_visible()
                            document = tomllib.loads(
                                (
                                    home / "server.toml" if name == "server" else config
                                ).read_text()
                            )
                            assert [
                                item["source"]
                                for item in document["contribs"]
                                if item["package"].startswith(package)
                            ] == [source]
                # A real registry outage must not erase the remote host's installed cards.
                port = server.server_port
                await asyncio.to_thread(server.shutdown)
                await asyncio.to_thread(thread.join)
                server.server_close()
                installed = (
                    await boss.get(f"{served.url}/api/market/computers/{ref}/installed")
                ).json()
                unavailable = await boss.get(
                    f"{served.url}/ui/market/updates?computer={ref}&view=installed"
                )
                assert unavailable.status_code == 200, unavailable.text
                assert 'role="alert"' in unavailable.text
                assert "bazaar-contrib-market-example" in unavailable.text
                assert (
                    f'<span id="installed-count" hx-swap-oob="outerHTML">{len(installed)}</span>'
                    in unavailable.text
                )
                server = ThreadingHTTPServer(
                    ("127.0.0.1", port),
                    partial(Registry, directory=str(registry)),
                )
                thread = threading.Thread(target=server.serve_forever)
                thread.start()
                # The private registry now publishes a real second wheel.
                updated = next(wheels.glob("bazaar_contrib_market_example-0.2.0-*.whl"))
                shutil.copy(updated, files / updated.name)
                (simple / "index.html").write_text(
                    f'<a href="../../files/{wheel.name}">{wheel.name}</a>'
                    f'<a href="../../files/{updated.name}">{updated.name}</a>'
                )
                for name, selected, configuration, api in (
                    (
                        "server",
                        "server",
                        home / "server.toml",
                        f"{served.url}/api/market/server",
                    ),
                    (
                        "computer",
                        ref,
                        config,
                        f"{served.url}/api/market/computers/{ref}",
                    ),
                ):
                    await page.goto(
                        f"{served.url}/market?computer={selected}&view=installed&q=market-example"
                    )
                    frame = page.frame_locator("iframe.frame")
                    card = frame.locator(".package-card").filter(
                        has=frame.get_by_role(
                            "heading", name="market-example", exact=True
                        )
                    )
                    await card.get_by_role("heading").get_by_role("link").click()
                    await expect(frame.locator("#package h2")).to_have_text(
                        "bazaar-contrib-market-example"
                    )
                    enabled = await changed(page, card.get_by_role("switch"), boss, api)
                    assert enabled["phase"] == "complete" and enabled["applied"], (
                        enabled
                    )
                    await expect(card.get_by_role("switch")).to_have_attribute(
                        "aria-checked", "true"
                    )
                    before = tomllib.loads(configuration.read_text())
                    parameters = [
                        entry["config"]
                        for package in before["contribs"]
                        for entry in package["enabled"]
                        if entry["entry"] == "market-example"
                    ]
                    await expect(card.locator("button.update")).to_be_visible()
                    upgraded = await changed(
                        page, card.locator("button.update"), boss, api
                    )
                    assert upgraded["phase"] == "complete" and upgraded["installed"], (
                        upgraded
                    )
                    await expect(frame.locator("#package .version code")).to_have_text(
                        "0.2.0"
                    )
                    await expect(card.locator(".version")).to_have_text("0.2.0")
                    metadata = (
                        await boss.get(api + "/packages/bazaar-contrib-market-example")
                    ).json()
                    report[name]["updated"] = metadata["version"] == "0.2.0"
                    after = tomllib.loads(configuration.read_text())
                    assert [
                        entry["config"]
                        for package in after["contribs"]
                        for entry in package["enabled"]
                        if entry["entry"] == "market-example"
                    ] == parameters
                    await card.get_by_role("button", name="更多操作").click()
                    rejected = await changed(
                        page,
                        card.get_by_role("button", name="卸载 Contrib", exact=True),
                        boss,
                        api,
                    )
                    assert (
                        rejected["phase"] == "failed"
                        and not rejected["environment_changed"]
                    ), rejected
                    assert tomllib.loads(configuration.read_text()) == after
                    disabled = await changed(
                        page, card.get_by_role("switch"), boss, api
                    )
                    assert disabled["phase"] == "complete" and disabled["applied"], (
                        disabled
                    )
                    await expect(card.get_by_role("switch")).to_have_attribute(
                        "aria-checked", "false"
                    )
                    await card.get_by_role("button", name="更多操作").click()
                    removed = await changed(
                        page,
                        card.get_by_role("button", name="卸载 Contrib", exact=True),
                        boss,
                        api,
                    )
                    assert removed["phase"] == "complete" and removed["config_saved"], (
                        removed
                    )
                    await expect(frame.locator("#operation")).to_contain_text(
                        "Contrib 已卸载"
                    )
                    await expect(card).to_have_count(0)
                    await expect(frame.locator("#package h2")).to_have_count(0)
                    installed = (await boss.get(api + "/installed")).json()
                    report[name]["removed"] = all(
                        item["package"] != "bazaar-contrib-market-example"
                        for item in installed
                    )
                # A real public provider becomes available in agent setup after enabling it.
                await page.goto(
                    f"{served.url}/market?computer={ref}&view=catalog&q=codex"
                )
                frame = page.frame_locator("iframe.frame")
                await (
                    frame.get_by_role("heading", name="codex", exact=True)
                    .get_by_role("link")
                    .click()
                )
                async with page.expect_response(
                    lambda response: (
                        "/ui/market/install?" in response.url
                        and response.request.method == "POST"
                    )
                ) as submitted:
                    await frame.get_by_role("button", name="安装", exact=True).click()
                submitted = await submitted.value
                operation = parse_qs(urlsplit(submitted.headers["hx-push-url"]).query)[
                    "operation"
                ][0]
                await result(
                    boss,
                    f"{served.url}/api/market/computers/{ref}",
                    await boss.get(
                        f"{served.url}/api/market/computers/{ref}/operations/{operation}"
                    ),
                )
                await page.goto(
                    f"{served.url}/market?computer={ref}&view=installed&q=codex"
                )
                frame = page.frame_locator("iframe.frame")
                codex = frame.locator(".package-card").filter(
                    has=frame.get_by_role("heading", name="codex", exact=True)
                )
                enabled = await changed(
                    page,
                    codex.get_by_role("switch"),
                    boss,
                    f"{served.url}/api/market/computers/{ref}",
                )
                assert enabled["phase"] == "complete" and enabled["applied"], enabled
                await page.goto(f"{served.url}/agents/new")
                frame = page.frame_locator("iframe.frame")
                await frame.locator("input[name=name]").fill("Workshop assistant")
                await frame.locator(".pcp").filter(has_text="Install here").click()
                await frame.get_by_role(
                    "button", name="下一步：渠道", exact=True
                ).click()
                await frame.get_by_role(
                    "button", name="下一步：运行时", exact=True
                ).click()
                await expect(
                    frame.locator("button.pick[value='add:harness:codex']")
                ).to_be_visible()
                report["computer"]["provider_available"] = True
                assert other_config.read_bytes() == original
                after = (
                    await boss.get(
                        f"{served.url}/api/market/computers/{other}/installed"
                    )
                ).json()
                assert after == untouched
                report["other_unchanged"] = True
                (home / "result.json").write_text(json.dumps(report))
            await browser.close()
    finally:
        await asyncio.to_thread(server.shutdown)
        await asyncio.to_thread(thread.join)
        server.server_close()


if __name__ == "__main__":
    asyncio.run(exercise())
