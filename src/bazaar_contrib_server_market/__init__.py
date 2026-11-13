"""The market's target-scoped catalog and management endpoints."""

from __future__ import annotations

from contextlib import asynccontextmanager
lazy import asyncio
lazy from collections.abc import AsyncIterator
lazy from importlib.resources import files
lazy from pathlib import Path

from bazaar_contrib_config import CONFIGURATION
from bazaar_contrib_manager import CONTRIB_CATALOG, CONTRIB_MANAGER
from bazaar_contrib_server import SERVER, PermissionItem, SidebarItem
from bazaar_contrib_server_access import ACCESS
from bazaar_contrib_server_computer import COMPUTERS
from bazaar_contrib_status import CONTRIB_STATUS
from bazaar_core import Context, Contrib
lazy from starlette.applications import Starlette

lazy from .api import API, UPDATE, VIEW
lazy from .pages import Views
lazy from .service import Market

__all__ = ["market"]


@asynccontextmanager
async def lifespan(ctx: Context) -> AsyncIterator[None]:
    server = ctx.accept(SERVER)
    access = ctx.accept(ACCESS)
    computers = ctx.accept(COMPUTERS)
    service = Market(
        ctx.accept(CONTRIB_CATALOG),
        ctx.accept(CONTRIB_MANAGER),
        computers,
        ctx.accept(CONFIGURATION),
        ctx.accept(CONTRIB_STATUS),
    )
    api = API(server, access, computers, service)
    resources = Path(str(files(__name__))) / "resources"
    pages = await server.pages("market", __name__)
    views = Views(pages, api, service)
    icon = await asyncio.to_thread(
        (resources / "templates" / "market" / "store.svg").read_text, encoding="utf-8"
    )
    async with (
        server.module(
            "market",
            api=Starlette(routes=api.routes),
            ui=pages.application(views.routes),
            static=resources / "static",
            locales=resources / "locales",
        ),
        server.sidebar(
            SidebarItem(
                text="market.title",
                icon=icon,
                path="/market",
                group="server.sidebar.extensions",
                permission=VIEW,
                order=100,
            )
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
    accepts=[
        SERVER,
        ACCESS,
        COMPUTERS,
        CONTRIB_CATALOG,
        CONTRIB_MANAGER,
        CONFIGURATION,
        CONTRIB_STATUS,
    ],
    lifespan=lifespan,
)
