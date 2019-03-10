"""Manage remote UI connections."""
import asyncio
from datetime import datetime
import logging
import random
import ssl
from typing import Optional

import async_timeout
import attr
from snitun.exceptions import SniTunConnectionError
from snitun.utils.aes import generate_aes_keyset
from snitun.utils.aiohttp_client import SniTunClientAioHttp

from . import cloud_api
from .acme import AcmeClientError, AcmeHandler
from .utils import server_context_modern, utcnow, utc_from_timestamp

_LOGGER = logging.getLogger(__name__)


class RemoteError(Exception):
    """General remote error."""


class RemoteBackendError(RemoteError):
    """Backend problem with nabucasa API."""


class RemoteNotConnected(RemoteError):
    """Raise if a request need connection and we are not ready."""


@attr.s
class SniTunToken:
    """Handle snitun token."""

    fernet = attr.ib(type=bytes)
    aes_key = attr.ib(type=bytes)
    aes_iv = attr.ib(type=bytes)
    valid = attr.ib(type=datetime)


class RemoteUI:
    """Class to help manage remote connections."""

    def __init__(self, cloud):
        """Initialize cloudhooks."""
        self.cloud = cloud
        self._acme = None
        self._snitun = None
        self._snitun_server = None
        self._instance_domain = None
        self._reconnect_task = None
        self._token = None

        # Register start/stop
        cloud.iot.register_on_connect(self.load_backend)
        cloud.iot.register_on_disconnect(self.close_backend)

    @property
    def snitun_server(self) -> Optional[str]:
        """Return connected snitun server."""
        return self._snitun_server

    @property
    def instance_domain(self) -> Optional[str]:
        """Return instance domain."""
        return self._instance_domain

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

        # Extract data
        _LOGGER.debug("Retrieve instance data: %s", data)
        domain = data["domain"]
        email = data["email"]
        server = data["server"]

        # Set instance details for certificate
        self._acme = AcmeHandler(self.cloud, domain, email)

        # Domain changed / revoke CA
        ca_domain = await self._acme.get_common_name()
        if ca_domain is not None and ca_domain != domain:
            _LOGGER.warning("Invalid certificate found: %s", ca_domain)
            await self._acme.reset_acme()

        # Issue a certificate
        if not await self._acme.is_valid_certificate():
            try:
                await self._acme.issue_certificate()
            except AcmeClientError:
                _LOGGER.error("ACME certification fails. Please try later.")
                raise RemoteBackendError()
        self._instance_domain = domain

        # Setup snitun / aiohttp wrapper
        context = await self._create_context()
        self._snitun = SniTunClientAioHttp(
            self.cloud.client.aiohttp_runner,
            context,
            snitun_server=server,
            snitun_port=443,
        )
        self._snitun_server = server

        await self._snitun.start()
        self.cloud.run_task(self.connect())

    async def close_backend(self) -> None:
        """Close connections and shutdown backend."""
        if self._reconnect_task:
            self._reconnect_task.cancel()

        # Disconnect snitun
        if self._snitun:
            await self._snitun.stop()

        # Cleanup
        self._snitun = None
        self._acme = None
        self._token = None
        self._instance_domain = None
        self._snitun_server = None

    async def handle_connection_requests(self, caller_ip):
        """Handle connection requests."""
        if not self._snitun:
            _LOGGER.error("Can't handle request-connection without backend")
            raise RemoteNotConnected()

        if self._snitun.is_connected:
            return
        await self.connect()

    async def _refresh_snitun_token(self):
        """Handle snitun token."""
        if self._token and self._token.valid > utcnow():
            _LOGGER.debug("Don't need refresh snitun token")
            return

        # Generate session token
        aes_key, aes_iv = generate_aes_keyset()
        async with async_timeout.timeout(10):
            resp = await cloud_api.async_remote_token(self.cloud, aes_key, aes_iv)

        if resp.status != 200:
            raise RemoteBackendError()
        data = await resp.json()

        self._token = SniTunToken(
            data["token"].encode(), aes_key, aes_iv, utc_from_timestamp(data["valid"])
        )

    async def connect(self):
        """Connect to snitun server."""
        if not self._snitun:
            _LOGGER.error("Can't handle request-connection without backend")
            raise RemoteNotConnected()

        # Check if we already connected
        if self._snitun.is_connected:
            return

        try:
            await self._refresh_snitun_token()
            await self._snitun.connect(
                self._token.fernet, self._token.aes_key, self._token.aes_iv
            )
        except SniTunConnectionError:
            _LOGGER.error("Connection problem to snitun server")
        except RemoteBackendError:
            _LOGGER.error("Can't refresh the snitun token")
        finally:
            # start retry task
            if not self._reconnect_task:
                self._reconnect_task = self.cloud.run_task(self._reconnect_snitun())

    async def disconnect(self):
        """Disconnect from snitun server."""
        if not self._snitun:
            _LOGGER.error("Can't handle request-connection without backend")
            raise RemoteNotConnected()

        # Stop reconnect task
        if self._reconnect_task:
            self._reconnect_task.cancel()

        # Check if we already connected
        if not self._snitun.is_connected:
            return
        await self._snitun.disconnect()

    async def _reconnect_snitun(self):
        """Reconnect after disconnect."""
        try:
            while True:
                if self._snitun.is_connected:
                    await self._snitun.wait()

                await asyncio.sleep(random.randint(1, 15))
                await self.connect()
        except asyncio.CancelledError:
            pass
        finally:
            self._reconnect_task = None
