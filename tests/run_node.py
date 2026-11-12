"""Run a configured node until its parent creates the stop file.

A blocking stdin reader prevents a child Python from starting on Windows when
it inherits that pipe. The test control stays separate from subprocess stdin.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from bazaar_compute_node.boot import node
from bazaar_contrib_config import Configuration
from blockbuster import blockbuster_ctx


async def serve():
    stop = Path(sys.argv[2]).with_suffix(".stop")
    async with node(configer=sys.argv[1], configer_options=(sys.argv[2],)) as hub:
        Configuration.check(hub, force=True)
        while not await asyncio.to_thread(stop.exists):  # noqa: ASYNC110 - Another process creates this file.
            await asyncio.sleep(0.1)


if __name__ == "__main__":
    with blockbuster_ctx():
        asyncio.run(serve())
