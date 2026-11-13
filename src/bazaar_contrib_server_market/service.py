"""Read and change the selected host through its own manager and catalog."""

from __future__ import annotations

lazy import asyncio
lazy import platform
lazy from typing import Any, Literal
lazy from uuid import UUID

from bazaar_contrib_config import (
    ConfigCandidate,
    ConfigDocument,
    ConfigSnapshot,
    Configuration,
)
from bazaar_contrib_manager import (
    CatalogEntry,
    ContribCatalog,
    ContribManager,
    IndexStatus,
    InstalledPackage,
    Operation,
    Package,
)
from bazaar_contrib_server_computer import Computers
from bazaar_contrib_status import ContribStatusQuery, Status
from pydantic import BaseModel, TypeAdapter

INDEXES = TypeAdapter(tuple[IndexStatus, ...])
ENTRIES = TypeAdapter(tuple[CatalogEntry, ...])
INSTALLED = TypeAdapter(tuple[InstalledPackage, ...])
STATES = TypeAdapter(tuple[Status, ...])
CONFIGURATION = TypeAdapter(tuple[ConfigCandidate, ConfigSnapshot | None])


class Host(BaseModel):
    system: str
    release: str
    machine: str


class Market:
    def __init__(
        self,
        catalog: ContribCatalog,
        manager: ContribManager,
        computers: Computers,
        configuration: Configuration,
        status: ContribStatusQuery,
    ) -> None:
        self._catalog = catalog
        self._manager = manager
        self._computers = computers
        self._configuration = configuration
        self._status = status

    async def configuration(self, computer: str | None) -> ConfigDocument:
        candidate, _ = (
            await self._configuration.read()
            if computer is None
            else CONFIGURATION.validate_python(
                await self._computers.call(computer, "configuration", "read")
            )
        )
        return ConfigDocument.model_validate(candidate.payload)

    async def states(self, computer: str | None) -> tuple[Status, ...]:
        if computer is None:
            return self._status.states()
        return STATES.validate_python(
            await self._computers.call(computer, "contrib-status", "states")
        )

    async def updates(self, computer: str | None) -> dict[str, str]:
        if computer is None:
            return await self._manager.updates()
        return TypeAdapter(dict[str, str]).validate_python(
            await self._computers.call(computer, "contrib-manager", "updates")
        )

    async def change(
        self,
        computer: str | None,
        method: Literal["enable", "disable", "upgrade", "remove"],
        *args: Any,
        **kwargs: Any,
    ) -> Operation:
        if computer is None:
            return await getattr(self._manager, method)(*args, **kwargs, wait=False)
        return Operation.model_validate(
            await self._computers.call(
                computer, "contrib-manager", method, *args, **kwargs, wait=False
            )
        )

    async def host(self, computer: str | None) -> Host:
        if computer is None:
            return await asyncio.to_thread(
                lambda: Host(
                    system=platform.system(),
                    release=platform.release(),
                    machine=platform.machine(),
                )
            )
        return Host.model_validate(await self._computers.call(computer, "node", "info"))

    async def indexes(self, computer: str | None) -> tuple[IndexStatus, ...]:
        if computer is None:
            return await self._catalog.indexes()
        return INDEXES.validate_python(
            await self._computers.call(computer, "contrib-catalog", "indexes")
        )

    async def entries(self, computer: str | None) -> tuple[CatalogEntry, ...]:
        if computer is None:
            return await self._catalog.entries()
        return ENTRIES.validate_python(
            await self._computers.call(computer, "contrib-catalog", "entries")
        )

    async def installed(self, computer: str | None) -> tuple[InstalledPackage, ...]:
        if computer is None:
            return await self._manager.installed()
        return INSTALLED.validate_python(
            await self._computers.call(computer, "contrib-manager", "installed")
        )

    async def detail(self, computer: str | None, name: str) -> InstalledPackage:
        if computer is None:
            return await self._manager.detail(name)
        return InstalledPackage.model_validate(
            await self._computers.call(computer, "contrib-manager", "detail", name)
        )

    async def add(self, computer: str | None, package: Package) -> Operation:
        if computer is None:
            return await self._manager.add(
                package.package, source=package.source, version=package.version
            )
        return Operation.model_validate(
            await self._computers.call(
                computer,
                "contrib-manager",
                "add",
                package.package,
                source=package.source,
                version=package.version,
            )
        )

    async def index(
        self, computer: str | None, location: str, *, remove: bool = False
    ) -> Operation:
        if computer is None:
            return await self._manager.index(location, remove=remove)
        return Operation.model_validate(
            await self._computers.call(
                computer, "contrib-manager", "index", location, remove=remove
            )
        )

    async def refresh(self, computer: str | None) -> tuple[IndexStatus, ...]:
        if computer is None:
            return await self._catalog.refresh()
        return INDEXES.validate_python(
            await self._computers.call(computer, "contrib-catalog", "refresh")
        )

    async def operation(self, computer: str | None, id: UUID) -> Operation:
        if computer is None:
            return await self._manager.operation(id)
        return Operation.model_validate(
            await self._computers.call(computer, "contrib-manager", "operation", id)
        )
