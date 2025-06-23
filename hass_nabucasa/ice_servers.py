"""Manage ICE servers."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
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
        self._ice_servers_listener: Callable[[], Awaitable[None]] | None = None
        self._ice_servers_listener_unregister: Callable[[], None] | None = None

    @property
    def hostname(self) -> str:
        """Get the hostname."""
        if TYPE_CHECKING:
            assert self._cloud.servicehandlers_server is not None
        return self._cloud.servicehandlers_server

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

            if self._ice_servers_listener is not None:
                await self._ice_servers_listener()

            sleep_time = self._get_refresh_sleep_time()
            await asyncio.sleep(sleep_time)

    def _on_add_listener(self) -> None:
        """When the instance is connected."""
        self._refresh_task = asyncio.create_task(
            self._async_refresh_nabucasa_ice_servers()
        )

    def _on_remove_listener(self) -> None:
        """When the instance is disconnected."""
        if self._refresh_task is not None:
            self._refresh_task.cancel()
            self._refresh_task = None

    def _get_ice_servers(self) -> list[RTCIceServer]:
        """Get ICE servers."""
        if self._cloud.subscription_expired:
            return []

        return [
            RTCIceServer(
                urls=server.urls,
                username=server.username,
                credential=server.credential,
            )
            for server in self._nabucasa_ice_servers
        ]

    async def async_register_ice_servers_listener(
        self,
        register_ice_server_fn: Callable[
            [list[RTCIceServer]],
            Awaitable[Callable[[], None]],
        ],
    ) -> Callable[[], None]:
        """Register a listener for ICE servers and return unregister function."""
        _LOGGER.debug("Registering ICE servers listener")

        async def perform_ice_server_update() -> None:
            """Perform ICE server update by unregistering and registering servers."""
            _LOGGER.debug("Updating ICE servers")

            if self._ice_servers_listener_unregister is not None:
                self._ice_servers_listener_unregister()
                self._ice_servers_listener_unregister = None

            ice_servers = self._get_ice_servers()
            self._ice_servers_listener_unregister = await register_ice_server_fn(
                ice_servers,
            )

            _LOGGER.debug("ICE servers updated")

        def remove_listener() -> None:
            """Remove listener."""
            if self._ice_servers_listener_unregister is not None:
                self._ice_servers_listener_unregister()
                self._ice_servers_listener_unregister = None

            self._nabucasa_ice_servers = []
            self._ice_servers_listener = None

            self._on_remove_listener()

        self._ice_servers_listener = perform_ice_server_update

        self._on_add_listener()

        return remove_listener
