"""Client interface for Home Assistant to cloud."""
from __future__ import annotations

from abc import ABC, abstractmethod
import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import aiohttp
from aiohttp import web

from .iot import HandlerError

if TYPE_CHECKING:
    from . import Cloud


class RemoteActivationNotAllowed(HandlerError):
    """Raised when it's not allowed to remotely activate remote UI."""

    def __init__(self) -> None:
        """Initialize Error Message."""
        super().__init__("remote_activation_not_allowed")


class CloudClient(ABC):
    """Interface class for Home Assistant."""

    cloud: Cloud

    @property
    @abstractmethod
    def base_path(self) -> Path:
        """Return path to base dir."""

    @property
    @abstractmethod
    def loop(self) -> asyncio.AbstractEventLoop:
        """Return client loop."""

    @property
    @abstractmethod
    def websession(self) -> aiohttp.ClientSession:
        """Return client session for aiohttp."""

    @property
    @abstractmethod
    def client_name(self) -> str:
        """Return name of the client, this will be used as the user-agent."""

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
    async def cloud_connected(self) -> None:
        """Called when cloud connected."""

    @abstractmethod
    async def cloud_disconnected(self) -> None:
        """Called when cloud disconnected."""

    @abstractmethod
    async def cloud_started(self) -> None:
        """Called when cloud started with active subscription."""

    @abstractmethod
    async def cloud_stopped(self) -> None:
        """Called when cloud is stopping."""

    @abstractmethod
    async def logout_cleanups(self) -> None:
        """Called on logout."""

    @abstractmethod
    async def async_cloud_connect_update(self, connect: bool) -> None:
        """Process cloud remote message to client.

        If it's not allowed to remotely enable remote control, the implementation
        should raise RemoteActivationNotAllowed
        """

    @abstractmethod
    async def async_cloud_connection_info(
        self, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Process cloud connection info message to client."""

    @abstractmethod
    async def async_alexa_message(self, payload: dict[str, Any]) -> dict[str, Any]:
        """process cloud alexa message to client."""

    @abstractmethod
    async def async_system_message(self, payload: dict[str, Any]) -> None:
        """process cloud system message to client."""

    @abstractmethod
    async def async_google_message(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Process cloud google message to client."""

    @abstractmethod
    async def async_webhook_message(self, payload: dict[str, Any]) -> dict[str, Any]:
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

    @abstractmethod
    async def async_create_repair_issue(
        self,
        identifier: str,
        translation_key: str,
        *,
        placeholders: dict[str, str] | None = None,
        severity: Literal["error", "warning"] = "warning",
    ) -> None:
        """Create a repair issue."""
