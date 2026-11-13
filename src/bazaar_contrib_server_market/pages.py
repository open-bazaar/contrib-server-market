"""The market in the server shell, scoped to the selected host."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlencode, urlsplit
from uuid import UUID

from bazaar_contrib_config import ConfigDocument
from bazaar_contrib_manager import ManagementError, Operation, Package
from bazaar_contrib_server import Pages
from bazaar_contrib_sidecar import RemoteError
from bazaar_contrib_status import Status
from pydantic import BaseModel, Field, ValidationError, model_validator
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response
from starlette.routing import Route

from .api import API, UPDATE, VIEW, IndexChange
from .service import Market

FINISHED = {"complete", "failed", "cancelled"}


class Selection(BaseModel):
    computer: str | None = None
    view: Literal["catalog", "installed", "indexes"] = "installed"
    source: str = ""
    state: Literal[
        "", "installed", "available", "active", "inactive", "failed", "updates"
    ] = ""
    q: str = ""
    package: str = ""
    index: str = ""
    operation: UUID | None = None

    def url(self, **changes: object) -> str:
        values = self.model_dump(mode="json") | changes
        return "/ui/market/?" + urlencode(
            {
                key: value
                for key, value in values.items()
                if value is not None and value != ""
            }
        )


@dataclass(frozen=True)
class Configured:
    index: int
    status: Status | None


class Change(BaseModel):
    action: Literal["enable", "disable", "upgrade", "remove"]
    package: str = Field(min_length=1)
    entry: str = ""
    index: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def position(self):
        if self.action == "disable" and self.index is None:
            raise ValueError("select a configured entry")
        return self


def source_label(source: str) -> str:
    if source.startswith("file:"):
        return "file://"
    if source == "https://pypi.org/simple/":
        return "PyPI"
    return urlsplit(source).netloc or source


class Views:
    def __init__(self, pages: Pages, api: API, market: Market) -> None:
        self._pages = pages
        self._api = api
        self._market = market
        self.routes = [
            Route("/", self.index),
            Route("/install", self.install, methods=["POST"]),
            Route("/indexes", self.indexes, methods=["POST"]),
            Route("/indexes/refresh", self.refresh, methods=["POST"]),
            Route("/operations/{id:uuid}", self.operation),
            Route("/updates", self.updates),
            Route("/packages", self.packages),
            Route("/targets", self.targets),
            Route("/change", self.change, methods=["POST"]),
        ]

    def _selection(self, request: Request) -> Selection:
        try:
            return Selection.model_validate(dict(request.query_params))
        except ValidationError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    async def _target(
        self, request: Request, selection: Selection, point: str
    ) -> str | None:
        return await self._api.target(
            request.state.account,
            None if selection.computer == "server" else selection.computer,
            point,
        )

    async def index(self, request: Request) -> Response:
        return await self._index(request)

    async def updates(self, request: Request) -> Response:
        return await self._index(request, check=True, fragment=True)

    async def packages(self, request: Request) -> Response:
        return await self._index(request, fragment=True)

    async def targets(self, request: Request) -> Response:
        selection = self._selection(request)
        targets = await self._api.accessible(request.state.account)
        details = {}
        async with asyncio.TaskGroup() as tasks:
            for target in targets.computers:
                if not target.online:
                    continue
                computer = await self._api.target(request.state.account, target.ref)
                details[target.ref] = (
                    tasks.create_task(self._market.host(computer)),
                    tasks.create_task(self._market.installed(computer)),
                    tasks.create_task(self._market.indexes(computer)),
                )
            if targets.server:
                details["server"] = (
                    tasks.create_task(self._market.host(None)),
                    tasks.create_task(self._market.installed(None)),
                    tasks.create_task(self._market.indexes(None)),
                )
        return await self._pages.render(
            request,
            "market/targets.html",
            selection=selection,
            url=selection.url,
            targets=targets,
            target_details={
                key: (host.result(), len(installed.result()), len(indexes.result()))
                for key, (host, installed, indexes) in details.items()
            },
        )

    async def _index(
        self,
        request: Request,
        *,
        check: bool = False,
        fragment: bool = False,
    ) -> Response:
        selection = self._selection(request)
        targets = await self._api.accessible(request.state.account)
        if selection.computer is None:
            selection = selection.model_copy(
                update={
                    "computer": targets.computers[0].ref
                    if targets.computers
                    else "server"
                    if targets.server
                    else None
                }
            )
        chosen = next(
            (item for item in targets.computers if item.ref == selection.computer), None
        )
        computer = None
        entries, installed, indexes = (), (), ()
        host = None
        document = ConfigDocument()
        states = ()
        updates = {}
        failure = None
        online = selection.computer == "server" or chosen is not None and chosen.online
        editable = (
            request.state.account.allows(UPDATE)
            if selection.computer == "server"
            else chosen.editable
            if chosen is not None
            else False
        )
        if selection.computer is not None:
            computer = await self._target(request, selection, VIEW)
            if online:
                try:
                    async with asyncio.TaskGroup() as tasks:
                        catalog = tasks.create_task(self._market.entries(computer))
                        packages = tasks.create_task(self._market.installed(computer))
                        subscriptions = tasks.create_task(
                            self._market.indexes(computer)
                        )
                        machine = tasks.create_task(self._market.host(computer))
                        configuration = tasks.create_task(
                            self._market.configuration(computer)
                        )
                        running = tasks.create_task(self._market.states(computer))
                    entries, installed, indexes = (
                        catalog.result(),
                        packages.result(),
                        subscriptions.result(),
                    )
                    host = machine.result()
                    document = configuration.result()
                    states = running.result()
                    if check:
                        updates = await self._market.updates(computer)
                except* (RemoteError, TimeoutError) as errors:
                    failure = str(errors.exceptions[0])
        kept = {item.package: item for item in installed}
        declarations = {
            item.distribution: item
            for item in document.contribs
            if item.package and item.applies
        }
        catalog = {
            item.package: item
            for item in entries
            if item.package not in declarations
            or not declarations[item.package].source
            or item.source == declarations[item.package].source
        }
        statuses = {item.location: item for item in states}
        enabled: dict[str, list[Configured]] = {}
        position = 0
        for index, declaration in enumerate(document.contribs):
            for place, entry in enumerate(declaration.enabled):
                enabled.setdefault(entry.entry, []).append(
                    Configured(
                        position,
                        statuses.get(f"contribs[{index}].enabled[{place}]"),
                    )
                )
                position += 1
        active = {
            item.package
            for item in installed
            if any(entry.name in enabled for entry in item.entries)
        }
        failures = {
            item.package
            for item in installed
            if any(
                entry.error
                or any(
                    instance.status and instance.status.error
                    for instance in enabled.get(entry.name, ())
                )
                for entry in item.entries
            )
        }
        sources = sorted({item.source for item in entries})
        listed = [
            item
            for item in entries
            if (not selection.source or item.source == selection.source)
            and (
                selection.state not in ("installed", "available")
                or (item.package in kept) == (selection.state == "installed")
            )
            and (
                not selection.q
                or selection.q.casefold()
                in (item.package + " " + (item.summary or "")).casefold()
            )
        ]
        listed_installed = [
            item
            for item in installed
            if (
                not selection.source
                or item.url == selection.source
                or item.package in catalog
                and catalog[item.package].source == selection.source
            )
            and (
                not selection.state
                or selection.state == "active"
                and item.package in active
                or selection.state == "inactive"
                and item.package not in active
                or selection.state == "failed"
                and item.package in failures
                or selection.state == "updates"
                and item.package in updates
            )
            and (
                not selection.q
                or selection.q.casefold()
                in (
                    item.package
                    + " "
                    + (
                        catalog[item.package].summary or ""
                        if item.package in catalog
                        else ""
                    )
                ).casefold()
            )
        ]
        selected = next(
            (
                item
                for item in entries
                if item.package == selection.package
                and (not selection.source or item.source == selection.source)
            ),
            None,
        )
        if selection.package in kept and not selection.source:
            selected = catalog.get(selection.package)
        operation = None
        package = None
        if selection.package in kept and online:
            package = await self._market.detail(computer, selection.package)
        if selection.operation is not None and online:
            operation = await self._market.operation(computer, selection.operation)
        return await self._pages.render(
            request,
            "market/packages.html" if fragment else "market/index.html",
            selection=selection,
            url=selection.url,
            targets=targets,
            chosen=chosen,
            host=host,
            target_details={selection.computer: (host, len(installed), len(indexes))}
            if host is not None
            else {},
            online=online,
            editable=editable,
            entries=listed,
            installed=installed,
            listed_installed=listed_installed,
            catalog=catalog,
            kept=kept,
            active=active,
            failures=failures,
            enabled=enabled,
            declarations=declarations,
            updates=updates,
            checked=check,
            fragment=fragment,
            indexes=indexes,
            selected_index=next(
                (item for item in indexes if item.location == selection.index), None
            ),
            index_entries=tuple(
                item for item in entries if selection.index in item.indexes
            ),
            sources=sources,
            source_label=source_label,
            selected=selected,
            failure=failure,
            operation=operation,
            finished=FINISHED,
            package=package,
            operation_package=kept.get(operation.package)
            if operation and operation.package
            else None,
        )

    async def _progress(
        self, request: Request, selection: Selection, operation: Operation
    ) -> Response:
        package = None
        if (
            operation.phase == "complete"
            and operation.installed
            and operation.package
            and operation.kind != "remove"
        ):
            computer = await self._target(request, selection, VIEW)
            package = await self._market.detail(computer, operation.package)
        response = await self._pages.render(
            request,
            "market/operation.html",
            selection=selection,
            url=selection.url,
            operation=operation,
            finished=FINISHED,
            package=package,
        )
        if operation.phase == "complete" and operation.kind in {
            "add",
            "enable",
            "disable",
            "upgrade",
            "remove",
        }:
            response.headers["HX-Trigger"] = "market:changed"
        return response

    async def install(self, request: Request) -> Response:
        selection = self._selection(request)
        computer = await self._target(request, selection, UPDATE)
        try:
            package = Package.model_validate(dict(await request.form()))
            operation = await self._market.add(computer, package)
        except (ValidationError, ManagementError) as error:
            return await self._pages.render(
                request, "market/message.html", error=str(error)
            )
        response = await self._progress(request, selection, operation)
        response.headers["HX-Push-Url"] = selection.url(operation=str(operation.id))
        return response

    async def change(self, request: Request) -> Response:
        selection = self._selection(request)
        computer = await self._target(request, selection, UPDATE)
        try:
            change = Change.model_validate(dict(await request.form()))
            match change.action:
                case "enable":
                    operation = await self._market.change(
                        computer, "enable", change.package, contrib=change.entry or None
                    )
                case "disable":
                    operation = await self._market.change(
                        computer, "disable", change.index
                    )
                case "upgrade" | "remove":
                    operation = await self._market.change(
                        computer, change.action, change.package
                    )
        except (ValidationError, ManagementError) as error:
            return await self._pages.render(
                request, "market/message.html", error=str(error)
            )
        response = await self._progress(request, selection, operation)
        response.headers["HX-Push-Url"] = selection.url(
            operation=str(operation.id),
            package="" if change.action == "remove" else selection.package,
        )
        return response

    async def indexes(self, request: Request) -> Response:
        selection = self._selection(request)
        computer = await self._target(request, selection, UPDATE)
        try:
            change = IndexChange.model_validate(dict(await request.form()))
        except ValidationError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        operation = await self._market.index(
            computer, change.location, remove=change.remove
        )
        return RedirectResponse(
            selection.url(operation=str(operation.id)), status_code=303
        )

    async def refresh(self, request: Request) -> Response:
        selection = self._selection(request)
        computer = await self._target(request, selection, UPDATE)
        await self._market.refresh(computer)
        return RedirectResponse(selection.url(), status_code=303)

    async def operation(self, request: Request) -> Response:
        selection = self._selection(request)
        computer = await self._target(request, selection, VIEW)
        operation = await self._market.operation(computer, request.path_params["id"])
        return await self._progress(request, selection, operation)
