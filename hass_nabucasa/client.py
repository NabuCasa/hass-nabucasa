"""Client interface for Home Assistant to cloud."""
from abc import ABC, abstractmethod
import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Optional

import aiohttp
from aiohttp import web

if TYPE_CHECKING:
    from . import Cloud  # noqa


class CloudClient(ABC):
    """Interface class for Home Assistant."""

    cloud: Optional["Cloud"] = None

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
    def aiohttp_runner(self) -> web.AppRunner:
        """Return client webinterface aiohttp application."""

    @property
    @abstractmethod
    def cloudhooks(self) -> Dict[str, Dict[str, str]]:
        """Return list of cloudhooks."""

    @property
    @abstractmethod
    def remote_autostart(self) -> bool:
        """Return true if we want start a remote connection."""

    @abstractmethod
    async def logged_in(self) -> None:
        """Called on log in."""

    @abstractmethod
    async def cleanups(self) -> None:
        """Called on logout."""

    @abstractmethod
    async def async_alexa_message(self, payload: Dict[Any, Any]) -> Dict[Any, Any]:
        """process cloud alexa message to client."""

    @abstractmethod
    async def async_google_message(self, payload: Dict[Any, Any]) -> Dict[Any, Any]:
        """Process cloud google message to client."""

    @abstractmethod
    async def async_webhook_message(self, payload: Dict[Any, Any]) -> Dict[Any, Any]:
        """Process cloud webhook message to client."""

    @abstractmethod
    async def async_cloudhooks_update(self, data: Dict[str, Dict[str, str]]) -> None:
        """Update local list of cloudhooks."""

    @abstractmethod
    def dispatcher_message(self, identifier: str, data: Any = None) -> None:
        """Send data to dispatcher."""

    @abstractmethod
    def user_message(self, identifier: str, title: str, message: str) -> None:
        """Create a message for user to UI."""
