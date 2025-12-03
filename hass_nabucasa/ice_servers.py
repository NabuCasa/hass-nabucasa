"""Manage ICE servers."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
import random
import time
from typing import TYPE_CHECKING, Any

from aiohttp import ClientResponseError
from webrtc_models import RTCIceServer

from .api import ApiBase, CloudApiError, api_exception_handler

if TYPE_CHECKING:
    from . import Cloud, _ClientT


_LOGGER = logging.getLogger(__name__)


class IceServersApiError(CloudApiError):
    """Exception raised when handling ICE servers API."""


@dataclass
class NabucasaIceServer(RTCIceServer):
    """ICE server for Nabucasa."""

    expiration_timestamp: int | None = None

    def __init__(self, data: dict[str, Any]) -> None:
        """Initialize Nabucasa ICE server."""
        super().__init__(
            urls=data["urls"],
            username=data.get("username"),
            credential=data.get("credential"),
        )

        if (ttl := data.get("ttl")) is not None:
            self.expiration_timestamp = int(time.time()) + ttl


class IceServers(ApiBase):
    """Class to manage ICE servers."""

    def __init__(self, cloud: Cloud[_ClientT]) -> None:
        """Initialize ICE Servers."""
        super().__init__(cloud)
        self._refresh_task: asyncio.Task | None = None
        self._nabucasa_ice_servers: list[NabucasaIceServer] = []
        self._initial_fetch_event: asyncio.Event | None = None

    @property
    def hostname(self) -> str:
        """Get the hostname."""
        if TYPE_CHECKING:
            assert self._cloud.servicehandlers_server is not None
        return self._cloud.servicehandlers_server

    @property
    def ice_servers(self) -> list[RTCIceServer]:
        """Get the current ICE servers."""
        return [
            RTCIceServer(
                urls=server.urls,
                username=server.username,
                credential=server.credential,
            )
            for server in self._nabucasa_ice_servers
        ]

    @api_exception_handler(IceServersApiError)
    async def _async_fetch_ice_servers(self) -> list[NabucasaIceServer]:
        """Fetch ICE servers."""
        if self._cloud.subscription_expired:
            return []
        response: list[dict] = await self._call_cloud_api(
            path="/webrtc/ice_servers",
            api_version=2,
        )
        return [NabucasaIceServer(item) for item in response]

    def _get_refresh_sleep_time(self) -> int:
        """Get the sleep time for refreshing ICE servers."""
        timestamps = [
            server.expiration_timestamp
            for server in self._nabucasa_ice_servers
            if server.expiration_timestamp is not None
        ]

        if not timestamps:
            return random.randint(3600, 3600 * 12)  # 1-12 hours

        if (expiration := min(timestamps) - int(time.time()) - 3600) < 0:
            return random.randint(100, 300)

        # 1 hour before the earliest expiration
        return expiration

    async def _async_refresh_nabucasa_ice_servers(self) -> None:
        """Handle Nabucasa ICE server refresh."""
        while True:
            try:
                self._nabucasa_ice_servers = await self._async_fetch_ice_servers()
            except IceServersApiError as err:
                _LOGGER.error("Can't refresh ICE servers: %s", err)

                # We should not keep the existing ICE servers with old timestamps
                # as that will retrigger a refresh almost immediately.
                if (
                    isinstance(err.orig_exc, CloudApiError)
                    and isinstance(err.orig_exc.orig_exc, ClientResponseError)
                    and err.orig_exc.orig_exc.status in (401, 403)
                ):
                    self._nabucasa_ice_servers = []

            except asyncio.CancelledError:
                # Task is canceled, stop it.
                break

            if self._initial_fetch_event is not None:
                self._initial_fetch_event.set()
                self._initial_fetch_event = None

            sleep_time = self._get_refresh_sleep_time()
            await asyncio.sleep(sleep_time)

    async def async_start(self) -> None:
        """Start the ICE servers refresh task."""
        if not self._cloud.is_logged_in or self._cloud.subscription_expired:
            return
        if self._refresh_task is None or self._refresh_task.done():
            self._initial_fetch_event = asyncio.Event()
            self._refresh_task = asyncio.create_task(
                self._async_refresh_nabucasa_ice_servers()
            )
            if self._initial_fetch_event is not None:
                await self._initial_fetch_event.wait()

    async def async_stop(self) -> None:
        """Stop the ICE servers refresh task."""
        if self._refresh_task is not None:
            self._refresh_task.cancel()
            self._refresh_task = None
        self._nabucasa_ice_servers = []
        self._initial_fetch_event = None
