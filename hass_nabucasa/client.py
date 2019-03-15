"""Client interface for Home Assistant to cloud."""
import asyncio
from pathlib import Path
from typing import Dict, Any

import aiohttp


class CloudClient:
    """Interface class for Home Assistant."""

    @property
    def base_path(self) -> Path:
        """Return path to base dir."""
        raise NotImplementedError()

    @property
    def loop(self) -> asyncio.BaseEventLoop:
        """Return client loop."""
        raise NotImplementedError()

    @property
    def websession(self) -> aiohttp.ClientSession:
        """Return client session for aiohttp."""
        raise NotImplementedError()

    @property
    def aiohttp_runner(self) -> aiohttp.web.AppRunner:
        """Return client webinterface aiohttp application."""
        raise NotImplementedError()

    @property
    def cloudhooks(self) -> Dict[str, Dict[str, str]]:
        """Return list of cloudhooks."""
        raise NotImplementedError()

    @property
    def remote_autostart(self) -> bool:
        """Return true if we want start a remote connection."""
        raise NotImplementedError()

    async def cleanups(self) -> None:
        """Called on logout."""
        raise NotImplementedError()

    async def async_alexa_message(self, payload: Dict[Any, Any]) -> Dict[Any, Any]:
        """process cloud alexa message to client."""
        raise NotImplementedError()

    async def async_google_message(self, payload: Dict[Any, Any]) -> Dict[Any, Any]:
        """Process cloud google message to client."""
        raise NotImplementedError()

    async def async_webhook_message(self, payload: Dict[Any, Any]) -> Dict[Any, Any]:
        """Process cloud webhook message to client."""
        raise NotImplementedError()

    async def async_cloudhooks_update(self, data: Dict[str, Dict[str, str]]) -> None:
        """Update local list of cloudhooks."""
        raise NotImplementedError()

    def dispatcher_message(self, identifier: str, data: Any = None) -> None:
        """Send data to dispatcher."""
        raise NotImplementedError()

    def user_message(self, identifier: str, title: str, message: str) -> None:
        """Create a message for user to UI."""
        raise NotImplementedError()
