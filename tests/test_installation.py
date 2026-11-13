"""Wheel-installed hosts install packages through the actual market pages."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


async def run(*arguments: str, environment: dict[str, str] | None = None) -> None:
    __tracebackhide__ = True
    process = await asyncio.create_subprocess_exec(
        *arguments,
        env=environment,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    output, _ = await process.communicate()
    assert process.returncode == 0, output.decode()


async def test_installs_from_pypi_and_private_index_on_selected_hosts(home: Path):
    root = ROOT
    wheels = home / "wheels"
    await run(
        "uv",
        "build",
        "--wheel",
        "--no-sources",
        "--directory",
        str(root),
        "--out-dir",
        str(wheels),
    )
    await run(
        "uv",
        "build",
        "--wheel",
        "--directory",
        str(root / "tests/fixtures/example"),
        "--out-dir",
        str(wheels),
    )
    updated = home / "example-update"
    await asyncio.to_thread(shutil.copytree, root / "tests/fixtures/example", updated)
    manifest = updated / "pyproject.toml"
    text = await asyncio.to_thread(manifest.read_text)
    await asyncio.to_thread(
        manifest.write_text, text.replace('version = "0.1.0"', 'version = "0.2.0"')
    )
    await run(
        "uv", "build", "--wheel", "--directory", str(updated), "--out-dir", str(wheels)
    )
    manifest = tomllib.loads(
        await asyncio.to_thread((root / "pyproject.toml").read_text)
    )
    dependencies = [
        f"{name} @ git+{source['git']}@{source['rev']}#subdirectory={source['subdirectory']}"
        for name, source in manifest["tool"]["uv"]["sources"].items()
    ]
    market = await asyncio.to_thread(
        lambda: next(wheels.glob("bazaar_contrib_server_market-*.whl"))
    )
    pythons = []
    for name in ("server", "computer", "other"):
        environment = home / (name + "-env")
        await run("uv", "venv", "--python", sys.executable, str(environment))
        python = environment / (
            "Scripts/python.exe" if os.name == "nt" else "bin/python"
        )
        await run(
            "uv",
            "pip",
            "install",
            "--python",
            str(python),
            "--prerelease",
            "allow",
            "bazaar-compute[node]==0.3.0rc31",
            "bazaar-contrib-server-agent==0.3.0rc12",
            "bazaar-contrib-starlink~=0.3.0rc1",
            "bazaar-contrib-sqlite~=0.3.0rc1",
            str(market),
            *dependencies,
            "httpx>=0.28.0,<1",
            "tomli-w",
            "blockbuster>=1.5.29,<1.6",
            "playwright==1.64.1",
        )
        pythons.append(python)
    await run(
        str(pythons[0]),
        str(root / "tests/installation_smoke.py"),
        str(home / "run"),
        str(pythons[1]),
        str(pythons[2]),
        str(wheels),
        environment={
            key: value
            for key, value in os.environ.items()
            if not key.startswith("BCN_")
        }
        | {"BCN_HOME": str(home / "run")},
    )
    report = json.loads(await asyncio.to_thread((home / "run/result.json").read_text))
    assert report["server"]["private"] == report["computer"]["private"] == "0.1.0"
    assert report["server"]["public"] and report["computer"]["public"]
    assert report["server"]["updated"] and report["computer"]["updated"]
    assert report["server"]["removed"] and report["computer"]["removed"]
    assert report["computer"]["provider_available"]
    assert report["other_unchanged"]
