"""Read and change the selected host through its own manager and catalog."""

from __future__ import annotations

lazy from uuid import UUID

from bazaar_contrib_manager import (
    CatalogEntry,
    ContribCatalog,
    ContribManager,
    IndexStatus,
    InstalledPackage,
    Operation,
)
from bazaar_contrib_server_computer import Computers
from pydantic import TypeAdapter

INDEXES = TypeAdapter(tuple[IndexStatus, ...])
ENTRIES = TypeAdapter(tuple[CatalogEntry, ...])
INSTALLED = TypeAdapter(tuple[InstalledPackage, ...])


class Market:
    def __init__(
        self, catalog: ContribCatalog, manager: ContribManager, computers: Computers
    ) -> None:
        self._catalog = catalog
        self._manager = manager
        self._computers = computers

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
