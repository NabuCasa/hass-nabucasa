"""Interface for Home Assistant to cloud."""
import asyncio
from pathlib import Path

import aiohttp


class CloudInterface:
    """Interface class for Home Assistant."""

    @property
    def base_dir(self) -> Path:
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
    def app(self) -> aiohttp.web.Application:
        """Return client webinterface aiohttp application."""
        raise NotImplementedError()

    async def async_user_message(self, identifier, title, message):
        """Create a message for user to UI."""
        raise NotImplementedError()

    async def async_alexa_message(self, payload):
        """process cloud alexa message to client."""
        raise NotImplementedError()

    async def async_google_message(self, payload):
        """Process cloud google message to client."""
        raise NotImplementedError()

    async def async_webhook_message(self, payload):
        """Process cloud webhook message to client."""
        raise NotImplementedError()
