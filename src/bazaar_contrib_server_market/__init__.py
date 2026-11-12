"""The market's target-scoped catalog and management endpoints."""

from __future__ import annotations

from contextlib import asynccontextmanager
lazy from collections.abc import AsyncIterator
lazy from importlib.resources import files
lazy from pathlib import Path

from bazaar_contrib_manager import CONTRIB_CATALOG, CONTRIB_MANAGER
from bazaar_contrib_server import SERVER, PermissionItem
from bazaar_contrib_server_access import ACCESS
from bazaar_contrib_server_computer import COMPUTERS
from bazaar_core import Context, Contrib
lazy from starlette.applications import Starlette

lazy from .api import API, UPDATE, VIEW
lazy from .service import Market

__all__ = ["market"]


@asynccontextmanager
async def lifespan(ctx: Context) -> AsyncIterator[None]:
    server = ctx.accept(SERVER)
    access = ctx.accept(ACCESS)
    computers = ctx.accept(COMPUTERS)
    service = Market(
        ctx.accept(CONTRIB_CATALOG), ctx.accept(CONTRIB_MANAGER), computers
    )
    api = API(server, access, computers, service)
    resources = Path(str(files(__name__))) / "resources"
    async with (
        server.module(
            "market", api=Starlette(routes=api.routes), locales=resources / "locales"
        ),
        server.permission(
            PermissionItem(point=VIEW, description="market.permission.view")
        ),
        server.permission(
            PermissionItem(point=UPDATE, description="market.permission.update")
        ),
        access.points("computer", (VIEW, UPDATE)),
    ):
        yield


market = Contrib(
    accepts=[SERVER, ACCESS, COMPUTERS, CONTRIB_CATALOG, CONTRIB_MANAGER],
    lifespan=lifespan,
)
