"""Client interface for Home Assistant to cloud."""
from abc import abstractmethod, ABC
import asyncio
from pathlib import Path
from typing import Dict, Any, TYPE_CHECKING

import aiohttp
from aiohttp import web

if TYPE_CHECKING:
    from . import Cloud


class CloudClient(ABC):
    """Interface class for Home Assistant."""

    @property
    @abstractmethod
    def base_path(self) -> Path:
        """Return path to base dir."""
        raise NotImplementedError()

    @property
    @abstractmethod
    def loop(self) -> asyncio.BaseEventLoop:
        """Return client loop."""
        raise NotImplementedError()

    @property
    @abstractmethod
    def websession(self) -> aiohttp.ClientSession:
        """Return client session for aiohttp."""
        raise NotImplementedError()

    @property
    @abstractmethod
    def aiohttp_runner(self) -> web.AppRunner:
        """Return client webinterface aiohttp application."""
        raise NotImplementedError()

    @property
    @abstractmethod
    def cloudhooks(self) -> Dict[str, Dict[str, str]]:
        """Return list of cloudhooks."""
        raise NotImplementedError()

    @property
    @abstractmethod
    def remote_autostart(self) -> bool:
        """Return true if we want start a remote connection."""
        raise NotImplementedError()

    @abstractmethod
    async def async_initialize(self, cloud: "Cloud") -> None:
        """Initialize the client."""
        raise NotImplementedError()

    @abstractmethod
    async def logged_in(self) -> None:
        """Called on log in."""
        raise NotImplementedError()

    @abstractmethod
    async def cleanups(self) -> None:
        """Called on logout."""
        raise NotImplementedError()

    @abstractmethod
    async def async_alexa_message(self, payload: Dict[Any, Any]) -> Dict[Any, Any]:
        """process cloud alexa message to client."""
        raise NotImplementedError()

    @abstractmethod
    async def async_google_message(self, payload: Dict[Any, Any]) -> Dict[Any, Any]:
        """Process cloud google message to client."""
        raise NotImplementedError()

    @abstractmethod
    async def async_webhook_message(self, payload: Dict[Any, Any]) -> Dict[Any, Any]:
        """Process cloud webhook message to client."""
        raise NotImplementedError()

    @abstractmethod
    async def async_cloudhooks_update(self, data: Dict[str, Dict[str, str]]) -> None:
        """Update local list of cloudhooks."""
        raise NotImplementedError()

    @abstractmethod
    def dispatcher_message(self, identifier: str, data: Any = None) -> None:
        """Send data to dispatcher."""
        raise NotImplementedError()

    @abstractmethod
    def user_message(self, identifier: str, title: str, message: str) -> None:
        """Create a message for user to UI."""
        raise NotImplementedError()
