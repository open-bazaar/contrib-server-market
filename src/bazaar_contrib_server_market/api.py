"""Market requests authorized for the computer they name, or for the server."""

from __future__ import annotations

from bazaar_contrib_manager import Package
from pydantic import BaseModel, ConfigDict, ValidationError
lazy from bazaar_contrib_server import Account, Server
lazy from bazaar_contrib_server_access import Access
lazy from bazaar_contrib_server_computer import Computers
lazy from starlette.exceptions import HTTPException
lazy from starlette.requests import Request
lazy from starlette.responses import JSONResponse, Response
lazy from starlette.routing import Route

lazy from .service import Market

VIEW = "contribs.view"
UPDATE = "contribs.update"


class IndexChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    location: str
    remove: bool = False


class Computer(BaseModel):
    ref: str
    name: str
    online: bool
    editable: bool


class Targets(BaseModel):
    server: bool
    computers: tuple[Computer, ...]


class API:
    def __init__(
        self, server: Server, access: Access, computers: Computers, market: Market
    ) -> None:
        self._server = server
        self._access = access
        self._computers = computers
        self._market = market
        self.routes = [Route("/targets", self.targets)]
        for prefix in ("/server", "/computers/{ref}"):
            self.routes.extend(
                [
                    Route(f"{prefix}/indexes", self.indexes),
                    Route(f"{prefix}/indexes", self.index, methods=["POST"]),
                    Route(f"{prefix}/indexes/refresh", self.refresh, methods=["POST"]),
                    Route(f"{prefix}/catalog", self.entries),
                    Route(f"{prefix}/installed", self.installed),
                    Route(f"{prefix}/packages/{{name}}", self.detail),
                    Route(f"{prefix}/install", self.install, methods=["POST"]),
                    Route(f"{prefix}/operations/{{id:uuid}}", self.operation),
                ]
            )

    async def targets(self, request: Request) -> Response:
        return JSONResponse(
            (await self.accessible(request.state.account)).model_dump(mode="json")
        )

    async def accessible(self, account: Account) -> Targets:
        if not account.allows(VIEW):
            raise HTTPException(status_code=403)
        allowed = await self._access.targets(account, "computer", VIEW)
        computers = await self._computers.computers(
            None if allowed is None else tuple(allowed)
        )
        await self._server.refs.load(computer.id for computer in computers)
        return Targets(
            server=account.admin,
            computers=tuple(
                [
                    Computer(
                        ref=str(self._server.refs.ref(computer.id)),
                        name=computer.name,
                        online=computer.online,
                        editable=await self._access.can(
                            account, "computer", computer.id, UPDATE
                        ),
                    )
                    for computer in computers
                ]
            ),
        )

    async def _target(self, request: Request, point: str = VIEW) -> str | None:
        return await self.target(
            request.state.account, request.path_params.get("ref"), point
        )

    async def target(
        self, account: Account, ref: str | None, point: str = VIEW
    ) -> str | None:
        if not account.allows(point):
            raise HTTPException(status_code=403)
        if ref is None:
            if not account.admin:
                raise HTTPException(status_code=403)
            return None
        values = await self._server.refs.values([ref])
        if values is None or not await self._access.can(
            account, "computer", values[0], point
        ):
            raise HTTPException(status_code=404)
        if not await self._computers.computers([values[0]]):
            raise HTTPException(status_code=404)
        return values[0]

    async def indexes(self, request: Request) -> Response:
        computer = await self._target(request)
        return JSONResponse(
            [
                item.model_dump(mode="json")
                for item in await self._market.indexes(computer)
            ]
        )

    async def entries(self, request: Request) -> Response:
        computer = await self._target(request)
        return JSONResponse(
            [
                item.model_dump(mode="json")
                for item in await self._market.entries(computer)
            ]
        )

    async def installed(self, request: Request) -> Response:
        computer = await self._target(request)
        return JSONResponse(
            [
                item.model_dump(mode="json")
                for item in await self._market.installed(computer)
            ]
        )

    async def detail(self, request: Request) -> Response:
        computer = await self._target(request)
        package = await self._market.detail(computer, request.path_params["name"])
        return JSONResponse(package.model_dump(mode="json"))

    async def install(self, request: Request) -> Response:
        computer = await self._target(request, UPDATE)
        try:
            package = Package.model_validate_json(await request.body())
        except ValidationError as error:
            return JSONResponse({"error": str(error)}, status_code=422)
        operation = await self._market.add(computer, package)
        return JSONResponse(operation.model_dump(mode="json"))

    async def index(self, request: Request) -> Response:
        computer = await self._target(request, UPDATE)
        try:
            change = IndexChange.model_validate_json(await request.body())
        except ValidationError as error:
            return JSONResponse({"error": str(error)}, status_code=422)
        operation = await self._market.index(
            computer, change.location, remove=change.remove
        )
        return JSONResponse(operation.model_dump(mode="json"))

    async def refresh(self, request: Request) -> Response:
        computer = await self._target(request, UPDATE)
        return JSONResponse(
            [
                item.model_dump(mode="json")
                for item in await self._market.refresh(computer)
            ]
        )

    async def operation(self, request: Request) -> Response:
        computer = await self._target(request)
        operation = await self._market.operation(computer, request.path_params["id"])
        return JSONResponse(operation.model_dump(mode="json"))
