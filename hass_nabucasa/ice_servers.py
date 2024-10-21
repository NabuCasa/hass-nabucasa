"""Class to manage ICE servers."""

import asyncio
from collections.abc import Awaitable, Callable
import logging
import time
from typing import TYPE_CHECKING, TypedDict

from aiohttp import ClientResponseError
from aiohttp.hdrs import AUTHORIZATION, USER_AGENT

if TYPE_CHECKING:
    from . import Cloud, _ClientT


_LOGGER = logging.getLogger(__name__)


class IceServer(TypedDict):
    """ICE Server."""

    urls: str
    username: str
    credential: str


class IceServersListener(TypedDict):
    """ICE Servers Listener."""

    register_ice_server_fn: Callable[[list[IceServer]], Awaitable[None]]
    servers_unregister: list[Callable[[], None]]


class IceServers:
    """Class to manage ICE servers."""

    def __init__(self, cloud: Cloud[_ClientT]) -> None:
        """Initialize ICE Servers."""
        self.cloud = cloud
        self._refresh_task: asyncio.Task | None = None
        self._ice_servers: list[IceServer] = []
        self._ice_servers_listeners: dict[str, IceServersListener] = {}

        cloud.iot.register_on_connect(self.on_connect)
        cloud.iot.register_on_disconnect(self.on_disconnect)

    async def _async_fetch_ice_servers(self) -> None:
        """Fetch ICE servers."""
        async with self.cloud.websession.get(
            f"https://{self.cloud.servicehandlers_server}/webrtc/ice_servers",
            headers={
                AUTHORIZATION: self.cloud.id_token,
                USER_AGENT: self.cloud.client.client_name,
            },
        ) as resp:
            if resp.status >= 400:
                _LOGGER.error("Failed to fetch ICE servers: %s", resp.status)

            resp.raise_for_status()
            data: list[IceServer] = await resp.json()

        self._ice_servers = data

        for listener_id in self._ice_servers_listeners:
            await self._perform_ice_server_listener_update(listener_id)

    def _get_refresh_sleep_time(self) -> int:
        """Get the sleep time for refreshing ICE servers."""
        timestamps = [
            int(server["username"].split(":")[0])
            for server in self._ice_servers
            if server["urls"].startswith("turn:")
        ]

        if not timestamps:
            return 3600  # 1 hour

        # 1 hour before the earliest expiration
        return min(timestamps) - int(time.time()) - 3600

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

    async def on_connect(self) -> None:
        """When the instance is connected."""
        self._refresh_task = asyncio.create_task(self._async_refresh_ice_servers())

    async def on_disconnect(self) -> None:
        """When the instance is disconnected."""
        if self._refresh_task is not None:
            self._refresh_task.cancel()
            self._refresh_task = None

    async def _perform_ice_server_listener_update(self, listener_id: str) -> None:
        """Perform ICE server listener update."""
        _LOGGER.debug("Performing ICE servers listener update: %s", listener_id)

        listener_obj = self._ice_servers_listeners.get(listener_id)
        if listener_obj is None:
            return

        register_ice_server_fn = listener_obj["register_ice_server_fn"]
        servers_unregister = listener_obj["servers_unregister"]

        for unregister in servers_unregister:
            await unregister()

        if not self._ice_servers:
            self._ice_servers_listeners[listener_id]["servers_unregister"] = []
            return

        self._ice_servers_listeners[listener_id]["servers_unregister"] = [
            await register_ice_server_fn(ice_server) for ice_server in self._ice_servers
        ]

        _LOGGER.debug("ICE servers listener update done: %s", str(self._ice_servers))

    async def async_register_ice_servers_listener(
        self,
        register_ice_server_fn: Callable[[list[IceServer]], Awaitable[None]],
    ) -> None:
        """Register a listener for ICE servers."""
        listener_id = str(id(register_ice_server_fn))

        _LOGGER.debug("Registering ICE servers listener: %s", listener_id)

        def remove_listener() -> None:
            """Remove listener."""
            self._ice_servers_listeners.pop(listener_id, None)

        self._ice_servers_listeners[listener_id] = {
            "register_ice_server_fn": register_ice_server_fn,
            "servers_unregister": [],
        }

        await self._perform_ice_server_listener_update(listener_id)

        return remove_listener
