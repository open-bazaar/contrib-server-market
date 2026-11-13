"""The pages and navigation through the real server and its roles."""

from pathlib import Path

from served import admin, client, role, serving, through


async def test_navigation_empty_guide_and_permissions(home: Path):
    async with (
        serving(home) as served,
        client() as boss,
        client() as reader,
        client() as stranger,
    ):
        await admin(served, boss)
        viewers = await role(
            served, boss, "market readers", "contribs.view", "computers.create"
        )
        await boss.post(f"{served.url}{viewers}/default")
        await through(served, reader, "reader")
        nobody = await role(served, boss, "no market")
        await boss.post(f"{served.url}{nobody}/default")
        await through(served, stranger, "stranger")

        shell = await reader.get(f"{served.url}/market")
        assert shell.status_code == 200
        assert 'href="/market"' in shell.text
        assert "Extensions" in shell.text
        empty = await reader.get(f"{served.url}/ui/market/")
        assert empty.status_code == 200, empty.text
        assert "Connect a computer to get started" in empty.text
        assert 'href="/computers"' in empty.text
        assert (
            await reader.get(f"{served.url}/ui/market/?computer=server")
        ).status_code == 403
        assert (
            await reader.get(f"{served.url}/ui/market/?computer=999999")
        ).status_code == 404
        assert (await stranger.get(f"{served.url}/ui/market/")).status_code == 403
        hidden = await stranger.get(f"{served.url}/market")
        assert 'href="/market"' not in hidden.text

        baseline = (home / "server.toml").read_bytes()
        rejected = await reader.post(
            f"{served.url}/ui/market/install?computer=server",
            data={
                "package": "bazaar-contrib-timer",
                "source": "https://pypi.org/simple/",
            },
        )
        assert rejected.status_code == 403
        assert (home / "server.toml").read_bytes() == baseline


async def test_catalog_detail_and_installed_metadata(home: Path):
    async with serving(home) as served, client() as boss:
        await admin(served, boss)
        page = await boss.get(f"{served.url}/ui/market/?computer=server")
        assert page.status_code == 200, page.text
        assert "bazaar-contrib-manager" in page.text
        detail = await boss.get(
            f"{served.url}/ui/market/",
            params={
                "computer": "server",
                "package": "bazaar-contrib-manager",
                "source": "https://pypi.org/simple/",
            },
        )
        assert detail.status_code == 200, detail.text
        assert "Version requirement" in detail.text
        assert "contrib-manager" in detail.text
        assert "Dependency compatibility" in detail.text
        installed = await boss.get(
            f"{served.url}/ui/market/?computer=server&view=installed"
        )
        assert installed.status_code == 200, installed.text
        assert "server-market" in installed.text
        assert "contrib-manager" in installed.text
        baseline = (home / "server.toml").read_bytes()
        invalid = await boss.post(
            f"{served.url}/ui/market/install?computer=server",
            data={
                "package": "bazaar-contrib-timer",
                "source": "https://pypi.org/simple/",
                "version": "not a version",
            },
        )
        assert invalid.status_code == 200
        assert "The request could not be submitted" in invalid.text
        assert (home / "server.toml").read_bytes() == baseline
