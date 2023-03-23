"""Client interface for Home Assistant to cloud."""
from __future__ import annotations

from abc import ABC, abstractmethod
import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any

import aiohttp
from aiohttp import web

if TYPE_CHECKING:
    from . import Cloud


class CloudClient(ABC):
    """Interface class for Home Assistant."""

    cloud: Cloud | None = None

    @property
    @abstractmethod
    def base_path(self) -> Path:
        """Return path to base dir."""

    @property
    @abstractmethod
    def loop(self) -> asyncio.BaseEventLoop:
        """Return client loop."""

    @property
    @abstractmethod
    def websession(self) -> aiohttp.ClientSession:
        """Return client session for aiohttp."""

    @property
    @abstractmethod
    def aiohttp_runner(self) -> web.AppRunner | None:
        """Return client webinterface aiohttp application."""

    @property
    @abstractmethod
    def cloudhooks(self) -> dict[str, dict[str, str | bool]]:
        """Return list of cloudhooks."""

    @property
    @abstractmethod
    def remote_autostart(self) -> bool:
        """Return true if we want start a remote connection."""

    @abstractmethod
    async def cloud_started(self) -> None:
        """Called when cloud started with active subscription ."""

    @abstractmethod
    async def cloud_stopped(self) -> None:
        """Called when cloud is stopping."""

    @abstractmethod
    async def logout_cleanups(self) -> None:
        """Called on logout."""

    @abstractmethod
    async def async_cloud_connect_update(self, connect: bool) -> None:
        """Process cloud remote message to client."""

    @abstractmethod
    async def async_alexa_message(self, payload: dict[Any, Any]) -> dict[Any, Any]:
        """process cloud alexa message to client."""

    @abstractmethod
    async def async_system_message(self, payload: dict[Any, Any]) -> None:
        """process cloud system message to client."""

    @abstractmethod
    async def async_google_message(self, payload: dict[Any, Any]) -> dict[Any, Any]:
        """Process cloud google message to client."""

    @abstractmethod
    async def async_webhook_message(self, payload: dict[Any, Any]) -> dict[Any, Any]:
        """Process cloud webhook message to client."""

    @abstractmethod
    async def async_cloudhooks_update(
        self,
        data: dict[str, dict[str, str | bool]],
    ) -> None:
        """Update local list of cloudhooks."""

    @abstractmethod
    def dispatcher_message(self, identifier: str, data: Any = None) -> None:
        """Send data to dispatcher."""

    @abstractmethod
    def user_message(self, identifier: str, title: str, message: str) -> None:
        """Create a message for user to UI."""
