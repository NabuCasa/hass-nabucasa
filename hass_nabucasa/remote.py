"""Manage remote UI connections."""
import asyncio
from contextlib import suppress
import logging
import random
import ssl
from typing import Optional

import async_timeout
from homeassistant.util.ssl import server_context_modern
from snitun.utils.aes import generate_aes_keyset
from snitun.utils.aiohttp_client import SniTunClientAioHttp

from . import cloud_api
from .acme import AcmeClientError, AcmeHandler

_LOGGER = logging.getLogger(__name__)


class RemoteError(Exception):
    """General remote error."""


class RemoteBackendError(RemoteError):
    """Backend problem with nabucasa API."""


class RemoteNotConnected(RemoteError):
    """Raise if a request need connection and we are not ready."""


class RemoteUI:
    """Class to help manage remote connections."""

    def __init__(self, cloud):
        """Initialize cloudhooks."""
        self.cloud = cloud
        self._acme = None
        self._snitun = None
        self._snitun_server = None
        self._reconnect_task = None

        # Register start/stop
        cloud.iot.register_on_connect(self.load_backend)
        cloud.iot.register_on_disconnect(self.close_backend)

    @property
    def snitun_server(self) -> Optional[str]:
        """Return connected snitun server."""
        return self._snitun_server

    async def _create_context(self) -> ssl.SSLContext:
        """Create SSL context with acme certificate."""
        context = server_context_modern()

        await self.cloud.run_executor(
            context.load_cert_chain,
            str(self._acme.path_fullchain),
            str(self._acme.path_private_key),
        )

        return context

    async def load_backend(self) -> None:
        """Load backend details."""
        if self._snitun:
            return

        # Load instance data from backend
        async with async_timeout.timeout(10):
            resp = await cloud_api.async_remote_register(self.cloud)

        if resp.status != 200:
            _LOGGER.error("Can't update remote details from Home Assistant cloud")
            raise RemoteBackendError()
        data = await resp.json()

        _LOGGER.debug("Retrieve instance data: %s", data)

        # Set instance details for certificate
        self._acme = AcmeHandler(self.cloud, data["domain"], data["email"])

        # Domain changed / revoke CA
        ca_domain = await self._acme.get_common_name()
        if ca_domain is not None and ca_domain != data["domain"]:
            _LOGGER.warning("Invalid certificate found")
            await self._acme.reset_acme()

        # Issue a certificate
        if not await self._acme.is_valid_certificate():
            try:
                await self._acme.issue_certificate()
            except AcmeClientError:
                _LOGGER.error("ACME certification fails. Please try later.")
                return

        # Setup snitun / aiohttp wrapper
        context = await self._create_context()
        self._snitun = SniTunClientAioHttp(
            self.cloud.client.aiohttp_runner,
            context,
            snitun_server=data["server"],
            snitun_port=443,
        )
        self._snitun_server = data["server"]

        await self._snitun.start()
        await self._connect_snitun()

    async def close_backend(self) -> None:
        """Close connections and shutdown backend."""
        if self._reconnect_task:
            self._reconnect_task.cancel()

        # Disconnect snitun
        if self._snitun:
            with suppress(RuntimeError):
                await self._snitun.stop()

        self._snitun = None
        self._acme = None

    async def handle_connection_requests(self, caller_ip):
        """Handle connection requests."""
        if not self._snitun:
            _LOGGER.error("Can't handle request-connection without backend")
            raise RemoteNotConnected()

        if self._snitun.is_connected:
            return

        await self._connect_snitun()

    async def _connect_snitun(self):
        """Connect to snitun server."""
        # Generate session token
        aes_key, aes_iv = generate_aes_keyset()
        async with async_timeout.timeout(10):
            resp = await cloud_api.async_remote_token(self.cloud, aes_key, aes_iv)

        if resp.status != 200:
            _LOGGER.error("Can't register a snitun token by server")
            raise RemoteBackendError()
        data = await resp.json()

        await self._snitun.connect(data["token"].encode(), aes_key, aes_iv)

        # start retry task
        if self._reconnect_task:
            return
        self._reconnect_task = self.cloud.run_task(self._reconnect_snitun())

    async def _reconnect_snitun(self):
        """Reconnect after disconnect."""
        try:
            while True:
                await self._snitun.wait()
                await asyncio.sleep(random.randint(1, 10))
                await self._connect_snitun()
        except asyncio.CancelledError:
            pass
        finally:
            self._reconnect_task = None
