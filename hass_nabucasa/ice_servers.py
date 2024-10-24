"""Manage ICE servers."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import logging
import random
import time
from typing import TYPE_CHECKING

from aiohttp import ClientResponseError
from aiohttp.hdrs import AUTHORIZATION, USER_AGENT
from webrtc_models import RTCIceServer

if TYPE_CHECKING:
    from . import Cloud, _ClientT


_LOGGER = logging.getLogger(__name__)


class IceServers:
    """Class to manage ICE servers."""

    def __init__(self, cloud: Cloud[_ClientT]) -> None:
        """Initialize ICE Servers."""
        self.cloud = cloud
        self._refresh_task: asyncio.Task | None = None
        self._ice_servers: list[RTCIceServer] = []
        self._ice_servers_listener: Callable[[], Awaitable[None]] | None = None
        self._ice_servers_listener_unregister: list[Callable[[], None]] = []

    async def _async_fetch_ice_servers(self) -> None:
        """Fetch ICE servers."""
        if TYPE_CHECKING:
            assert self.cloud.id_token is not None

        async with self.cloud.websession.get(
            f"https://{self.cloud.servicehandlers_server}/webrtc/ice_servers",
            headers={
                AUTHORIZATION: self.cloud.id_token,
                USER_AGENT: self.cloud.client.client_name,
            },
        ) as resp:
            resp.raise_for_status()

            self._ice_servers = [
                RTCIceServer(
                    urls=item["urls"],
                    username=item["username"],
                    credential=item["credential"],
                )
                for item in await resp.json()
            ]

        if self._ice_servers_listener is not None:
            await self._ice_servers_listener()

    def _get_refresh_sleep_time(self) -> int:
        """Get the sleep time for refreshing ICE servers."""
        timestamps = [
            int(server.username.split(":")[0])
            for server in self._ice_servers
            if server.urls.startswith("turn:")
        ]

        if not timestamps:
            return 3600  # 1 hour

        if (expiration := min(timestamps) - int(time.time()) - 3600) < 0:
            return random.randint(100, 300)

        # 1 hour before the earliest expiration
        return expiration

    async def _async_refresh_ice_servers(self) -> None:
        """Handle ICE server refresh."""
        while True:
            try:
                await self._async_fetch_ice_servers()
            except ClientResponseError as err:
                _LOGGER.error("Can't refresh ICE servers: %s", err)
            except asyncio.CancelledError:
                # Task is canceled, stop it.
                break

            sleep_time = self._get_refresh_sleep_time()
            await asyncio.sleep(sleep_time)

    def _on_add_listener(self) -> None:
        """When the instance is connected."""
        self._refresh_task = asyncio.create_task(self._async_refresh_ice_servers())

    def _on_remove_listener(self) -> None:
        """When the instance is disconnected."""
        if self._refresh_task is not None:
            self._refresh_task.cancel()
            self._refresh_task = None

    async def async_register_ice_servers_listener(
        self,
        register_ice_server_fn: Callable[[RTCIceServer], Awaitable[Callable[[], None]]],
    ) -> Callable[[], None]:
        """Register a listener for ICE servers."""
        _LOGGER.debug("Registering ICE servers listener")

        async def perform_ice_server_update() -> None:
            """Perform ICE server update."""
            _LOGGER.debug("Updating ICE servers")

            for unregister in self._ice_servers_listener_unregister:
                unregister()

            if not self._ice_servers:
                self._ice_servers_listener_unregister = []
                return

            self._ice_servers_listener_unregister = [
                await register_ice_server_fn(ice_server)
                for ice_server in self._ice_servers
            ]

            _LOGGER.debug("ICE servers updated")

        def remove_listener() -> None:
            """Remove listener."""
            for unregister in self._ice_servers_listener_unregister:
                unregister()

            self._ice_servers = []
            self._ice_servers_listener = None
            self._ice_servers_listener_unregister = []

            self._on_remove_listener()

        self._ice_servers_listener = perform_ice_server_update

        self._on_add_listener()

        return remove_listener
