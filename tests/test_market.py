"""The market through real HTTP, configuration storage and connected nodes."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tomllib
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

import httpx
import tomli_w
from bazaar_compute_node.boot import defaults
from served import admin, client, enrol, role, serving, through

FINISHED = {"complete", "failed", "cancelled"}


async def result(session: httpx.AsyncClient, url: str, response: httpx.Response):
    assert response.status_code == 200, response.text
    operation = response.json()
    while operation["phase"] not in FINISHED:
        await asyncio.sleep(0.1)
        response = await session.get(f"{url}/operations/{operation['id']}")
        assert response.status_code == 200, response.text
        operation = response.json()
    assert operation["phase"] == "complete", operation
    return operation


@asynccontextmanager
async def computer(served, session: httpx.AsyncClient, home: Path, name: str):
    ref, token = await enrol(served, session, name)
    await asyncio.to_thread(home.mkdir)
    config = home / "node.toml"
    document = await asyncio.to_thread(defaults)
    document["contrib_indexes"] = ["resource://bazaar_contrib_manager/catalog.json"]
    for package in document["contribs"]:
        for entry in package["enabled"]:
            if entry["entry"] == "sidecar-unix":
                entry["config"] = {
                    "endpoint": f"/tmp/bcn-market-{uuid4().hex[:12]}.sock"
                }
    document["contribs"].append(
        {
            "enabled": [
                {"entry": "starlink", "config": {"server": served.url, "token": token}}
            ]
        }
    )
    await asyncio.to_thread(config.write_text, tomli_w.dumps(document))
    log = await asyncio.to_thread((home / "node.log").open, "wb")
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        str(Path(__file__).with_name("run_node.py")),
        "config-filesystem",
        str(config),
        env=dict(os.environ)
        | {"BCN_HOME": str(home), "HOME": str(home), "USERPROFILE": str(home)},
        stdin=asyncio.subprocess.DEVNULL,
        stdout=log,
        stderr=asyncio.subprocess.STDOUT,
    )
    await asyncio.to_thread(log.close)
    try:
        while True:
            assert process.returncode is None, await asyncio.to_thread(
                (home / "node.log").read_text
            )
            answer = await session.get(f"{served.url}/api/market/targets")
            if any(
                item["ref"] == ref and item["online"]
                for item in answer.json()["computers"]
            ):
                break
            await asyncio.sleep(0.2)
        yield ref, config
    finally:
        if process.returncode is None:
            await asyncio.to_thread(config.with_suffix(".stop").touch)
            await process.wait()


async def test_server_catalog_and_subscription_operations(home: Path):
    async with serving(home) as served, client() as boss, client() as anonymous:
        await admin(served, boss)
        url = f"{served.url}/api/market/server"
        assert (await anonymous.get(f"{url}/catalog")).status_code in (302, 303, 401)
        targets = (await boss.get(f"{served.url}/api/market/targets")).json()
        assert targets["server"] and not targets["computers"]
        official = (await boss.get(f"{url}/catalog")).json()
        assert any(item["package"] == "bazaar-contrib-manager" for item in official)
        installed = (await boss.get(f"{url}/installed")).json()
        assert any(
            item["package"] == "bazaar-contrib-server-market" and item["version"]
            for item in installed
        )
        index = home / "extra.json"
        await asyncio.to_thread(
            index.write_text,
            json.dumps(
                {
                    "contribs": [
                        {
                            "package": "bazaar-contrib-manager",
                            "source": "https://pypi.org/simple/",
                            "summary": "The local catalog",
                        },
                        {
                            "package": "bazaar-contrib-manager",
                            "source": "https://packages.example.org/simple/",
                        },
                    ]
                }
            ),
        )
        operation = await result(
            boss, url, await boss.post(f"{url}/indexes", json={"location": str(index)})
        )
        assert operation["config_saved"]
        entries = (await boss.get(f"{url}/catalog")).json()
        package = [
            item for item in entries if item["package"] == "bazaar-contrib-manager"
        ]
        assert len(package) == 2
        official = next(
            item for item in package if item["source"] == "https://pypi.org/simple/"
        )
        assert official["summary"] == "The local catalog"
        assert str(index) in official["indexes"] and len(official["indexes"]) > 1
        assert official["description"] is None and official["icon_url"] is None
        config = home / "server.toml"
        assert (
            str(index)
            in tomllib.loads(await asyncio.to_thread(config.read_text))[
                "contrib_indexes"
            ]
        )
        unchanged = await asyncio.to_thread(config.read_bytes)
        assert (
            await boss.post(f"{url}/indexes", json={"location": 42})
        ).status_code == 422
        assert await asyncio.to_thread(config.read_bytes) == unchanged
        await result(
            boss,
            url,
            await boss.post(
                f"{url}/indexes", json={"location": str(index), "remove": True}
            ),
        )
        assert all(
            item["location"] != str(index)
            for item in (await boss.get(f"{url}/indexes")).json()
        )


async def test_shared_computer_market_permissions_and_target_storage(home: Path):
    async with (
        serving(home) as served,
        client() as boss,
        client() as owner,
        client() as reader,
        client() as editor,
        client() as outsider,
    ):
        await admin(served, boss)
        makers = await role(
            served,
            boss,
            "owners",
            "computers.view",
            "computers.create",
            "computers.share",
            "contribs.view",
            "contribs.update",
        )
        readers = await role(served, boss, "readers", "contribs.view")
        editors = await role(
            served, boss, "editors", "contribs.view", "contribs.update"
        )
        nobody = await role(served, boss, "none")
        for person, session, held in (
            ("owner", owner, makers),
            ("reader", reader, readers),
            ("editor", editor, editors),
            ("outsider", outsider, nobody),
        ):
            await boss.post(f"{served.url}{held}/default")
            await through(served, session, person)
        assert (
            await outsider.get(f"{served.url}/api/market/targets")
        ).status_code == 403
        assert not (await reader.get(f"{served.url}/api/market/targets")).json()[
            "computers"
        ]
        async with computer(served, owner, home / "computer", "My computer") as (
            ref,
            config,
        ):
            url = f"{served.url}/api/market/computers/{ref}"
            assert (await editor.get(f"{url}/catalog")).status_code == 404
            r, e = readers.rsplit("/", 1)[1], editors.rsplit("/", 1)[1]
            sharing = f"{served.url}/ui/access/shares/computer/{ref}"
            changed = await owner.post(
                sharing,
                data={
                    "roles": [r, e],
                    "grant": [f"{r} contribs.view", f"{e} contribs.view"],
                },
            )
            assert changed.status_code == 200
            for person in (reader, editor):
                target = (await person.get(f"{served.url}/api/market/targets")).json()
                assert not target["server"]
                assert any(
                    item["ref"] == ref and not item["editable"]
                    for item in target["computers"]
                )
                assert (await person.get(f"{url}/catalog")).status_code == 200
                assert (
                    await person.get(f"{served.url}/api/market/server/catalog")
                ).status_code == 403
            response = await reader.get(f"{url}/installed")
            assert response.status_code == 200, response.text
            installed = response.json()
            assert any(
                item["package"] == "bazaar-contrib-starlink" for item in installed
            )
            extra = home / "computer" / "custom.json"
            await asyncio.to_thread(
                extra.write_text,
                json.dumps(
                    {
                        "contribs": [
                            {
                                "package": "bazaar-contrib-timer",
                                "source": "https://pypi.org/simple/",
                                "summary": "On the selected computer",
                            }
                        ]
                    }
                ),
            )
            before = await asyncio.to_thread(config.read_bytes)
            server = await asyncio.to_thread((home / "server.toml").read_bytes)
            for person in (reader, editor, outsider):
                assert (
                    await person.post(f"{url}/indexes", json={"location": str(extra)})
                ).status_code in (403, 404)
            assert await asyncio.to_thread(config.read_bytes) == before
            await owner.post(
                sharing,
                data={
                    "roles": [r, e],
                    "grant": [
                        f"{r} contribs.view",
                        f"{e} contribs.view",
                        f"{e} contribs.update",
                    ],
                },
            )
            target = (await editor.get(f"{served.url}/api/market/targets")).json()
            assert any(
                item["ref"] == ref and item["editable"] for item in target["computers"]
            )
            operation = await result(
                editor,
                url,
                await editor.post(f"{url}/indexes", json={"location": str(extra)}),
            )
            assert operation["config_saved"]
            assert (
                str(extra)
                in tomllib.loads(await asyncio.to_thread(config.read_text))[
                    "contrib_indexes"
                ]
            )
            assert await asyncio.to_thread((home / "server.toml").read_bytes) == server
            entries = (await reader.get(f"{url}/catalog")).json()
            assert any(
                item["summary"] == "On the selected computer" for item in entries
            )
            assert (await editor.post(f"{url}/indexes/refresh")).status_code == 200
            await result(
                editor,
                url,
                await editor.post(
                    f"{url}/indexes", json={"location": str(extra), "remove": True}
                ),
            )
            assert (
                str(extra)
                not in tomllib.loads(await asyncio.to_thread(config.read_text))[
                    "contrib_indexes"
                ]
            )
            # Revoking the share removes visibility and editing immediately.
            await owner.post(
                sharing, data={"roles": [r, e], "grant": [f"{r} contribs.view"]}
            )
            assert not (await editor.get(f"{served.url}/api/market/targets")).json()[
                "computers"
            ]
            assert (
                await editor.get(f"{url}/operations/{operation['id']}")
            ).status_code == 404
            assert (
                await editor.post(f"{url}/indexes", json={"location": str(extra)})
            ).status_code == 404


async def test_http_index_cache_survives_a_source_error(home: Path):
    from functools import partial
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread

    index = home / "published.json"
    await asyncio.to_thread(
        index.write_text,
        json.dumps(
            {
                "contribs": [
                    {
                        "package": "bazaar-contrib-timer",
                        "source": "https://pypi.org/simple/",
                        "summary": "Published description",
                        "description": "## Timer",
                        "icon_url": "https://example.org/timer.svg",
                    }
                ]
            }
        ),
    )

    def start():
        http = ThreadingHTTPServer(
            ("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(home))
        )
        thread = Thread(target=http.serve_forever, daemon=True)
        thread.start()
        return http, thread

    http, thread = await asyncio.to_thread(start)
    try:
        async with serving(home) as served, client() as boss:
            await admin(served, boss)
            url = f"{served.url}/api/market/server"
            location = f"http://127.0.0.1:{http.server_port}/published.json"
            await result(
                boss,
                url,
                await boss.post(f"{url}/indexes", json={"location": location}),
            )
            entries = (await boss.get(f"{url}/catalog")).json()
            assert any(
                item["summary"] == "Published description"
                and item["description"] == "## Timer"
                and item["icon_url"] == "https://example.org/timer.svg"
                for item in entries
            )
            await asyncio.to_thread(index.rename, home / "withdrawn.json")
            refreshed = (await boss.post(f"{url}/indexes/refresh")).json()
            assert any(
                item["location"] == location
                and item["error"]
                and item["cached"]
                and item["entries"]
                for item in refreshed
            )
            cached = (await boss.get(f"{url}/indexes")).json()
            assert any(
                item["location"] == location and item["read_at"] and item["entries"]
                for item in cached
            )
            entries = (await boss.get(f"{url}/catalog")).json()
            assert any(
                item["summary"] == "Published description"
                and location in item["indexes"]
                for item in entries
            )
    finally:
        await asyncio.to_thread(http.shutdown)
        await asyncio.to_thread(http.server_close)
        await asyncio.to_thread(thread.join)
